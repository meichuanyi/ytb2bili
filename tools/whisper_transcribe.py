#!/usr/bin/env python3
import sys, json, os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from faster_whisper import WhisperModel

audio = sys.argv[1]
out_json = sys.argv[2]
model_dir = "/root/models/whisper"
m = WhisperModel("small", device="cpu", compute_type="int8", download_root=model_dir)
segments, info = m.transcribe(audio, beam_size=1, vad_filter=True, language=None)
raw = []
for s in segments:
    text = (s.text or "").strip()
    if not text:
        continue
    raw.append((float(s.start), float(s.end), text))

# merge into sentence-level chunks to avoid mid-sentence cuts
segs = []
cur_start, cur_end, cur_texts = None, None, []
def flush():
    global cur_start, cur_end, cur_texts
    if cur_texts:
        segs.append({"start": round(cur_start, 3), "end": round(cur_end, 3), "text": " ".join(cur_texts).strip()})
    cur_start, cur_end, cur_texts = None, None, []

max_dur = 12.0
end_punct = ("。", "！", "？", "；", ".", "!", "?", ";")
for st, en, text in raw:
    if cur_start is None:
        cur_start, cur_end, cur_texts = st, en, [text]
    else:
        cur_end = en
        cur_texts.append(text)
    joined = " ".join(cur_texts)
    if (cur_end - cur_start) >= max_dur or joined.endswith(end_punct):
        flush()
flush()

parts = [x["text"] for x in segs]
result = {
    "language": getattr(info, "language", "") or "",
    "full_text": " ".join(parts),
    "segments": segs,
}
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False)
print(json.dumps({"ok": True, "segments": len(segs), "language": result["language"]}))
