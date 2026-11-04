"""Narration synthesis + exact word-level alignment.

Uses the Kokoro-82M neural TTS (ONNX).  The stock ONNX graph is patched to
also return the duration predictor output ("/encoder/Clip_output_0"), i.e. the
number of 25 ms frames the model spends on every phoneme token.  Because those
are the durations the vocoder actually renders, the word timestamps derived
from them ARE the real timing of the generated speech (no approximation, no
external aligner needed).  1 frame = 600 samples @ 24 kHz.

Output: build/narration.wav, build/words.json
"""
import json, os, re, sys, urllib.request
import numpy as np, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODELS = os.environ.get("KOKORO_DIR", os.path.join(ROOT, "build", "models"))
BUILD = os.path.join(ROOT, "build")
SR, HOP = 24000, 600
VOICE, SPEED = "af_heart", 1.06

URLS = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}

sys.path.insert(0, HERE)
from narration import SENTENCES  # noqa: E402


def ensure_models():
    os.makedirs(MODELS, exist_ok=True)
    for f, u in URLS.items():
        p = os.path.join(MODELS, f)
        if not os.path.exists(p):
            print("downloading", u)
            urllib.request.urlretrieve(u, p)
    dur = os.path.join(MODELS, "kokoro-dur.onnx")
    if not os.path.exists(dur):
        import onnx
        m = onnx.load(os.path.join(MODELS, "kokoro-v1.0.onnx"))
        m.graph.output.append(onnx.helper.make_tensor_value_info(
            "/encoder/Clip_output_0", onnx.TensorProto.FLOAT, None))
        onnx.save(m, dur)
    return dur


def parse(sentence):
    """'{claude dot ai|CLAUDE.AI}' -> spoken 'claude dot ai', shown as one word."""
    spoken, groups = [], []  # groups: (display, n_spoken_words)
    for m in re.finditer(r"\{([^|}]+)\|([^}]+)\}(\S*)|(\S+)", sentence):
        if m.group(4):
            spoken.append(m.group(4)); groups.append((m.group(4), 1))
        else:
            ws = m.group(1).split()
            ws[-1] += m.group(3)
            spoken += ws; groups.append((m.group(2) + m.group(3), len(ws)))
    return " ".join(spoken), groups


def main():
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    durp = ensure_models()
    k = Kokoro(os.path.join(MODELS, "kokoro-v1.0.onnx"), os.path.join(MODELS, "voices-v1.0.bin"))
    sess = ort.InferenceSession(durp)
    voices = k.get_voice_style(VOICE)

    audio, words, sents, t = [], [], [], 0.25  # 0.25 s lead-in
    audio.append(np.zeros(int(SR * 0.25), np.float32))
    for si, s in enumerate(SENTENCES):
        spoken, groups = parse(s["text"])
        ph = k.tokenizer.known(k.tokenizer.phonemize(spoken, "en-us"))
        pw = ph.split(" ")
        pw = [w for w in pw if w]
        n_sp = sum(n for _, n in groups)
        if len(pw) != n_sp:  # fall back to word-by-word phonemisation
            pw = [k.tokenizer.known(k.tokenizer.phonemize(w, "en-us")).strip() for w in spoken.split()]
            ph = " ".join(pw)
        assert len(pw) == n_sp, (s["text"], pw)
        toks = k.tokenizer.tokenize(ph)
        assert len(toks) == len(ph)
        out = sess.run(None, {"tokens": [[0, *toks, 0]], "style": voices[len(toks)],
                              "speed": np.array([s.get("speed", SPEED)], np.float32)})
        wav, dur = out[0].astype(np.float32), out[1][0].astype(int)
        assert len(wav) == dur.sum() * HOP
        cum = np.concatenate([[0], np.cumsum(dur)])  # cum[i] = start frame of token i
        # char index c in ph -> token index c+1
        spans, c = [], 0
        for w in pw:
            a, b = c, c + len(w)
            core = re.sub(r"[^\wɐ-˿æðøŋœ]+$", "", w)  # strip trailing punct
            b_core = a + max(1, len(core))
            spans.append((cum[a + 1], cum[b_core + 1]))
            c = b + 1
        f0, f1 = spans[0][0], spans[-1][1]
        a0 = max(0, f0 * HOP - int(0.04 * SR)); a1 = min(len(wav), f1 * HOP + int(0.10 * SR))
        seg = wav[a0:a1]
        fade = int(0.01 * SR); seg[:fade] *= np.linspace(0, 1, fade); seg[-fade:] *= np.linspace(1, 0, fade)
        base = t - a0 / SR
        wi, sw = 0, []
        for disp, n in groups:
            st = base + spans[wi][0] * HOP / SR
            en = base + spans[wi + n - 1][1] * HOP / SR
            sw.append({"w": disp, "s": round(st, 3), "e": round(en, 3), "si": si})
            wi += n
        words += sw
        sents.append({"i": si, "id": s["id"], "s": round(t, 3), "e": round(t + len(seg) / SR, 3), "text": s["text"]})
        audio.append(seg); t += len(seg) / SR
        gap = s.get("gap", 0.18)
        audio.append(np.zeros(int(SR * gap), np.float32)); t += int(SR * gap) / SR
        print(f"{si:2d} {sents[-1]['s']:6.2f}-{sents[-1]['e']:6.2f}  {spoken}")
    audio.append(np.zeros(int(SR * 1.2), np.float32))
    full = np.concatenate(audio)
    full = full / max(1e-6, np.abs(full).max()) * 0.89
    os.makedirs(BUILD, exist_ok=True)
    sf.write(os.path.join(BUILD, "narration.wav"), full, SR)
    json.dump({"duration": round(len(full) / SR, 3), "words": words, "sentences": sents},
              open(os.path.join(BUILD, "words.json"), "w"), indent=1)
    print("total", len(full) / SR)


if __name__ == "__main__":
    main()
