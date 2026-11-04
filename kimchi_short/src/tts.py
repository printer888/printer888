"""Generate narration with Kokoro (local neural TTS) + exact word timings.

The stock Kokoro ONNX graph is patched (see make_timed_model) to also output the
duration predictor's per-phoneme frame counts. One frame = 600 samples @ 24 kHz.
Word timestamps therefore come from the model that actually produced the audio —
no approximation, no separate aligner.

Outputs (build/):
  voice.wav        24 kHz mono narration
  words.json       [{text, spoken, kw, line, scene, start, end}]
  visemes.json     [[start, end, open, round], ...] phoneme-level mouth shapes
  lines.json       [{scene, start, end, text}]
"""
import json, os, re, sys
import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from script import LINES, VOICE, SPEED, LEAD_IN, TAIL  # noqa: E402

MODELS = os.path.join(ROOT, "models")
BUILD = os.path.join(ROOT, "build")
SR = 24000
HOP = 600

VOWELS = set("aeiouɑæʌɔəɜɚɪʊɛɐᵻɒoʏøœɤɯ")
ROUND = set("uʊoɔɒwʃʒ")
CLOSED = set("mbp")
LABIODENT = set("fv")


def make_timed_model():
    src = os.path.join(MODELS, "kokoro-v1.0.onnx")
    dst = os.path.join(MODELS, "kokoro-timed.onnx")
    if os.path.exists(dst):
        return dst
    import onnx
    m = onnx.load(src)
    m.graph.output.append(onnx.helper.make_tensor_value_info(
        "/encoder/Clip_output_0", onnx.TensorProto.FLOAT, None))
    onnx.save(m, dst)
    return dst


def parse_line(text):
    out = []
    for tok in text.split():
        kw = tok.startswith("*")
        tok = tok.lstrip("*")
        if "=" in tok:
            disp, spoken = tok.split("=", 1)
            # keep trailing punctuation of display on spoken too
            m = re.search(r"[.,!?;:]+$", disp)
            spoken = spoken.replace("_", " ") + (m.group(0) if m and not spoken.endswith(m.group(0)) else "")
        else:
            disp, spoken = tok, tok
        out.append(dict(text=disp, spoken=spoken, kw=kw))
    return out


def viseme(ch):
    if ch in VOWELS:
        o = 1.0 if ch in "aɑæʌɐ" else (0.55 if ch in "iɪeɛᵻ" else 0.75)
        return o, (1.0 if ch in ROUND else 0.0)
    if ch in CLOSED:
        return 0.0, 0.0
    if ch in LABIODENT:
        return 0.12, 0.0
    if ch in ROUND:
        return 0.35, 1.0
    if ch.isalpha() or ch in "ðθŋɹɾʔʤʧ":
        return 0.3, 0.0
    return None  # stress marks / punctuation / space


OVERRIDE = {"a": "ɐ", "kimchi": "kˈɪmtʃi"}


def phon(tokz, word):
    m = re.match(r"^(.*?)([.,!?;:]*)$", word)
    core, punct = m.group(1), m.group(2)
    if core.lower() in OVERRIDE:
        return OVERRIDE[core.lower()] + punct
    return tokz.phonemize(word)


def main():
    from kokoro_onnx import Kokoro
    model = make_timed_model()
    k = Kokoro(model, os.path.join(MODELS, "voices-v1.0.bin"))
    voice = k.get_voice_style(VOICE)
    tokz = k.tokenizer

    pieces, words, vis, lines = [], [], [], []
    t = LEAD_IN
    pieces.append(np.zeros(int(LEAD_IN * SR), np.float32))
    for li, (scene, text, pause) in enumerate(LINES):
        wl = parse_line(text)
        wph = []
        for w in wl:
            wph.append(" ".join(phon(tokz, s) for s in w["spoken"].split()))
        ph = " ".join(wph)
        toks = tokz.tokenize(ph)
        # token index range per word
        ranges, i = [], 0
        for p in wph:
            n = len(tokz.tokenize(p))
            ranges.append((i, i + n))
            i += n + 1  # + space
        assert i - 1 == len(toks), (i, len(toks), ph)
        style = voice[len(toks)]
        a, d = k.sess.run(None, {
            "tokens": np.array([[0, *toks, 0]], dtype=np.int64),
            "style": style,
            "speed": np.array([SPEED], dtype=np.float32)})
        a = a.ravel().astype(np.float32)
        d = d.ravel()
        edges = np.concatenate([[0], np.cumsum(d)]) * HOP / SR  # token k (padded) spans edges[k]..edges[k+1]
        # trim leading/trailing silence
        env = np.abs(a)
        thr = 0.02 * env.max()
        nz = np.where(env > thr)[0]
        s0 = max(0, nz[0] - int(0.03 * SR))
        s1 = min(len(a), nz[-1] + int(0.06 * SR))
        a = a[s0:s1]
        off = t - s0 / SR
        # fades to avoid clicks
        f = int(0.008 * SR)
        a[:f] *= np.linspace(0, 1, f); a[-f:] *= np.linspace(1, 0, f)
        for wi, (w, (r0, r1)) in enumerate(zip(wl, ranges)):
            st = edges[r0 + 1] + off
            en = edges[r1 + 1] + off
            words.append(dict(text=w["text"], spoken=w["spoken"], kw=w["kw"], line=li,
                              scene=scene, start=round(float(st), 3), end=round(float(en), 3)))
        for ti, tk in enumerate(ph):
            v = viseme(tk)
            if v is None:
                continue
            vis.append([round(float(edges[ti + 1] + off), 3), round(float(edges[ti + 2] + off), 3), v[0], v[1]])
        line_start = t
        pieces.append(a)
        t += len(a) / SR
        lines.append(dict(scene=scene, text=" ".join(w["text"] for w in wl),
                          start=round(line_start, 3), end=round(t, 3),
                          wstart=words[-len(wl)]["start"], wend=words[-1]["end"]))
        pieces.append(np.zeros(int(pause * SR), np.float32))
        t += pause
        print(f"{scene:9s} {line_start:6.2f}-{t:6.2f}  {ph[:70]}")
    pieces.append(np.zeros(int(TAIL * SR), np.float32))
    audio = np.concatenate(pieces)
    audio = audio / (np.abs(audio).max() + 1e-9) * 0.89
    os.makedirs(BUILD, exist_ok=True)
    sf.write(os.path.join(BUILD, "voice.wav"), audio, SR)
    meta = dict(duration=round(len(audio) / SR, 3), fps=30)
    for name, obj in [("words", words), ("visemes", vis), ("lines", lines), ("meta", meta)]:
        with open(os.path.join(BUILD, name + ".json"), "w") as fh:
            json.dump(obj, fh, indent=0 if name != "visemes" else None)
    print("duration", meta["duration"], "words", len(words))


if __name__ == "__main__":
    main()
