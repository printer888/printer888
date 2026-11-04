"""Character voices + exact word/phoneme timing for lip-sync.

Kokoro-82M (ONNX), patched to also output its duration predictor so every
phoneme's real start/end in the generated audio is known (25 ms frames).
Accents are produced at the phoneme level: the US-English IPA is rewritten with
Russian / Italian sound substitutions before synthesis, and each character always
uses the same voice embedding + speed + accent rules => identical voice identity.
Output: build/dialogue.wav, build/timeline.json
"""
import json, os, re, sys, urllib.request
import numpy as np, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
B = os.path.join(ROOT, "build"); MODELS = os.environ.get("KOKORO_DIR", os.path.join(B, "models"))
SR, HOP = 24000, 600
sys.path.insert(0, HERE)
from dialogue import CAST, LINES, TAIL  # noqa

URLS = {"kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
        "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"}

def ensure_models():
    os.makedirs(MODELS, exist_ok=True)
    for f, u in URLS.items():
        if not os.path.exists(os.path.join(MODELS, f)): urllib.request.urlretrieve(u, os.path.join(MODELS, f))
    dur = os.path.join(MODELS, "kokoro-dur.onnx")
    if not os.path.exists(dur):
        import onnx
        m = onnx.load(os.path.join(MODELS, "kokoro-v1.0.onnx"))
        m.graph.output.append(onnx.helper.make_tensor_value_info("/encoder/Clip_output_0", onnx.TensorProto.FLOAT, None))
        onnx.save(m, dur)
    return dur

PUNCT = ".,!?;:…—\"“”"
RULES = {
    # Russian-accented English: no dental fricatives, v for w, rolled r, x for h,
    # tense i for ɪ, no æ, final devoicing, plain t instead of the US flap.
    "ru": [("ɚ", "ɛr"), ("ɜː", "ɛr"), ("oʊ", "o"), ("eɪ", "ej"), ("aɪ", "aj"), ("ð", "z"), ("θ", "s"),
           ("w", "v"), ("ɹ", "r"), ("h", "x"), ("iː", "i"), ("ɪ", "i"), ("æ", "ɛ"), ("ʌ", "a"), ("uː", "u"),
           ("ʊ", "u"), ("ɑː", "a"), ("ɔː", "o"), ("ə", "ɐ"), ("ɾ", "t")],
    # Italian-accented English: dropped h, d/t for th, tapped/rolled r, pure vowels,
    # light final schwa on phrase-final stops ("work-a").
    "it": [("ɚ", "er"), ("ɜː", "ɛr"), ("oʊ", "o"), ("eɪ", "e"), ("ð", "d"), ("θ", "t"), ("h", ""),
           ("ɹ", "r"), ("iː", "i"), ("ɪ", "i"), ("æ", "ɛ"), ("ʌ", "a"), ("ə", "e"), ("uː", "u"), ("ʊ", "u"),
           ("ɑː", "a"), ("ɔː", "ɔ"), ("ɾ", "t")],
    "light": [("ɹ", "ɾ"), ("ð", "d")],
}
DEVOICE = {"d": "t", "z": "s", "v": "f", "ɡ": "k", "b": "p"}

def accent(word, kind, phrase_final):
    core = word.rstrip(PUNCT); tail = word[len(core):]
    for a, b in RULES[kind]:
        core = core.replace(a, b)
    if kind == "ru" and core and core[-1] in DEVOICE:
        core = core[:-1] + DEVOICE[core[-1]]
    if kind == "it" and phrase_final and core and core[-1] in "ptkdɡ" and len(core) > 2:
        core += "ɐ"
    if not core:
        core = "ɐ"
    return core + tail

def main():
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    durp = ensure_models()
    k = Kokoro(os.path.join(MODELS, "kokoro-v1.0.onnx"), os.path.join(MODELS, "voices-v1.0.bin"))
    sess = ort.InferenceSession(durp)
    audio, words, lines, t = [], [], [], 0.0
    for li, L in enumerate(LINES):
        c = CAST[L["who"]]; style = k.get_voice_style(c["voice"])
        pre = int(SR * L["pre"]); audio.append(np.zeros(pre, np.float32)); t += pre / SR
        spoken = L["text"].split()
        pw = [w for w in k.tokenizer.known(k.tokenizer.phonemize(L["text"], "en-us")).split(" ") if w]
        if len(pw) != len(spoken):  # fall back to word-by-word phonemisation
            pw = [k.tokenizer.known(k.tokenizer.phonemize(w, "en-us")).strip().replace(" ", "") for w in spoken]
        pw = [accent(w, c["accent"], i == len(pw) - 1 or spoken[i][-1] in ".!?…") for i, w in enumerate(pw)]
        ph = " ".join(pw); toks = k.tokenizer.tokenize(ph)
        assert len(toks) == len(ph), (ph, k.tokenizer.known(ph))
        out = sess.run(None, {"tokens": [[0, *toks, 0]], "style": style[len(toks)], "speed": np.array([c["speed"]], np.float32)})
        wav, dur = out[0].astype(np.float32), out[1][0].astype(int)
        cum = np.concatenate([[0], np.cumsum(dur)])
        a0 = max(0, cum[1] * HOP - int(0.03 * SR)); a1 = min(len(wav), cum[len(toks) + 1] * HOP + int(0.12 * SR))
        seg = wav[a0:a1].copy(); f = int(0.008 * SR); seg[:f] *= np.linspace(0, 1, f); seg[-f:] *= np.linspace(1, 0, f)
        base = t - a0 / SR; tt = lambda fr: round(base + fr * HOP / SR, 3)
        phones, ci = [], 0
        for wi, w in enumerate(pw):
            core_len = len(w.rstrip(PUNCT))
            ws, we = tt(cum[ci + 1]), tt(cum[ci + max(1, core_len) + 1])
            words.append({"w": spoken[wi], "s": ws, "e": we, "li": li, "who": L["who"]})
            for j, ch in enumerate(w):
                if ch not in "ˈˌː" + PUNCT:
                    phones.append([ch, tt(cum[ci + j + 1]), tt(cum[ci + j + 2])])
            ci += len(w) + 1
        lines.append({"i": li, "id": L["id"], "who": L["who"], "s": words[-len(pw)]["s"], "e": words[-1]["e"],
                      "text": L["text"], "ipa": ph, "phones": phones})
        audio.append(seg); t += len(seg) / SR
        print(f"{li:2d} {L['who']} {lines[-1]['s']:6.2f}-{lines[-1]['e']:6.2f} {ph}")
    tail = int(SR * TAIL); audio.append(np.zeros(tail, np.float32)); t += tail / SR
    full = np.concatenate(audio); full = full / np.abs(full).max() * 0.89
    sf.write(os.path.join(B, "dialogue.wav"), full, SR)
    # per-speaker stems (for panning/EQ in the mix)
    json.dump({"duration": round(len(full) / SR, 3), "cast": CAST, "words": words, "lines": lines},
              open(os.path.join(B, "timeline.json"), "w"), indent=1, ensure_ascii=False)
    print("total", round(len(full) / SR, 2))

if __name__ == "__main__":
    main()
