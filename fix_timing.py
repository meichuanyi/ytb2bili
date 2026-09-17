from pathlib import Path

# ── 1) dub_audio_step: non-overlapping sequential layout ──
p = Path("/root/projects/ytb2bili-main/internal/workflow/dub_audio_step.go")
s = p.read_text()

old = '''	// 收集有效配音片段
	clips := make([]dubClip, 0, len(vctx.SubtitleAudios))
	for _, sub := range vctx.SubtitleAudios {
		p := strings.TrimSpace(sub.AudioPath)
		if p == "" || strings.TrimSpace(sub.TranslatedText) == "" {
			continue
		}
		if _, err := os.Stat(p); err != nil {
			continue
		}
		start := sub.StartTime
		if start < 0 {
			start = 0
		}
		clips = append(clips, dubClip{path: p, startMs: int(start * 1000)})
	}
'''
new = '''	// 收集有效配音片段；按中文实际时长顺序排轨，避免下一句盖住未说完的话。
	type placedClip struct {
		dubClip
		idx     int
		endMs   int
		origMs  int
	}
	clips := make([]dubClip, 0, len(vctx.SubtitleAudios))
	placed := make([]placedClip, 0, len(vctx.SubtitleAudios))
	prevEndMs := 0
	const gapMs = 80
	for i := range vctx.SubtitleAudios {
		sub := &vctx.SubtitleAudios[i]
		p := strings.TrimSpace(sub.AudioPath)
		if p == "" || strings.TrimSpace(sub.TranslatedText) == "" {
			continue
		}
		if _, err := os.Stat(p); err != nil {
			continue
		}
		origStart := sub.StartTime
		if origStart < 0 {
			origStart = 0
		}
		origMs := int(origStart * 1000)
		durMs := audioDurationMs(ctx, s.ffmpegPath, p)
		if durMs <= 0 {
			// 退回原槽位长度估计
			origEnd := sub.EndTime
			if origEnd <= origStart {
				origEnd = origStart + 3
			}
			durMs = int((origEnd - origStart) * 1000)
		}
		startMs := origMs
		if startMs < prevEndMs+gapMs {
			startMs = prevEndMs + gapMs
		}
		endMs := startMs + durMs
		clips = append(clips, dubClip{path: p, startMs: startMs})
		placed = append(placed, placedClip{dubClip: clips[len(clips)-1], idx: i, endMs: endMs, origMs: origMs})
		prevEndMs = endMs
		// 回写时间轴，便于后续字幕与画面大致对齐
		sub.StartTime = float64(startMs) / 1000.0
		sub.EndTime = float64(endMs) / 1000.0
	}
	if len(placed) > 0 {
		s.logger.Info("配音轨道已按实际时长重排",
			zap.Int("clips", len(clips)),
			zap.Int("last_end_ms", prevEndMs),
			zap.Int("first_orig_ms", placed[0].origMs))
	}
'''
if old not in s:
    raise SystemExit("clip collect block not found")
s = s.replace(old, new, 1)

# add helper at end of file
if "func audioDurationMs" not in s:
    s += '''

func audioDurationMs(ctx context.Context, ffmpegPath, path string) int {
	// ffprobe 若不存在则用 ffmpeg 解析 duration
	probe := strings.Replace(ffmpegPath, "ffmpeg", "ffprobe", 1)
	if _, err := exec.LookPath(probe); err != nil {
		probe = "ffprobe"
	}
	if _, err := exec.LookPath(probe); err == nil {
		cmd := exec.CommandContext(ctx, probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path)
		out, err := cmd.Output()
		if err == nil {
			var sec float64
			if _, scanErr := fmt.Sscanf(strings.TrimSpace(string(out)), "%f", &sec); scanErr == nil && sec > 0 {
				return int(sec * 1000)
			}
		}
	}
	cmd := exec.CommandContext(ctx, ffmpegPath, "-i", path)
	b, _ := cmd.CombinedOutput()
	// parse Duration: 00:00:03.45
	re := regexp.MustCompile(`Duration: (\\d+):(\\d+):(\\d+\\.\\d+)`)
	m := re.FindStringSubmatch(string(b))
	if m == nil {
		return 0
	}
	h, _ := strconv.ParseFloat(m[1], 64)
	mm, _ := strconv.ParseFloat(m[2], 64)
	ss, _ := strconv.ParseFloat(m[3], 64)
	return int((h*3600 + mm*60 + ss) * 1000)
}
'''
# imports
if '"regexp"' not in s:
    s = s.replace('import (\n\t"context"\n\t"fmt"\n', 'import (\n\t"context"\n\t"fmt"\n\t"regexp"\n')
if '"strconv"' not in s:
    s = s.replace('\t"regexp"\n', '\t"regexp"\n\t"strconv"\n')
p.write_text(s)
print("dub_audio_step patched")

# ── 2) whisper: merge to sentence-level ──
p = Path("/root/projects/ytb2bili-main/tools/whisper_transcribe.py")
s = p.read_text()
s = s.replace('''segments, info = m.transcribe(audio, beam_size=1, vad_filter=True, language=None)
segs = []
parts = []
for s in segments:
    text = (s.text or "").strip()
    if not text:
        continue
    segs.append({"start": round(float(s.start), 3), "end": round(float(s.end), 3), "text": text})
    parts.append(text)
''', '''segments, info = m.transcribe(audio, beam_size=1, vad_filter=True, language=None)
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
''')
p.write_text(s)
print("whisper merge patched")

# ── 3) Go: merge transcript segments after Bcut/whisper ──
p = Path("/root/projects/ytb2bili-main/pkg/tools/bcut_transcriber.go")
s = p.read_text()
if "func MergeTranscriptSegments" not in s:
    helper = '''

// MergeTranscriptSegments 将碎句合并为句级字幕，降低「半句被下一句切掉」的概率。
func MergeTranscriptSegments(segments []TranscriptSegment, maxDurSec float64) []TranscriptSegment {
	if len(segments) == 0 {
		return segments
	}
	if maxDurSec <= 0 {
		maxDurSec = 12
	}
	out := make([]TranscriptSegment, 0, len(segments))
	var cur *TranscriptSegment
	flush := func() {
		if cur != nil && strings.TrimSpace(cur.Text) != "" {
			out = append(out, *cur)
		}
		cur = nil
	}
	endPunct := []string{"。", "！", "？", "；", ".", "!", "?", ";"}
	for _, seg := range segments {
		text := strings.TrimSpace(seg.Text)
		if text == "" {
			continue
		}
		if cur == nil {
			tmp := seg
			tmp.Text = text
			cur = &tmp
		} else {
			cur.Text = strings.TrimSpace(cur.Text + " " + text)
			if seg.End > cur.End {
				cur.End = seg.End
			}
		}
		ended := false
		for _, p := range endPunct {
			if strings.HasSuffix(cur.Text, p) {
				ended = true
				break
			}
		}
		if ended || (cur.End-cur.Start) >= maxDurSec {
			flush()
		}
	}
	flush()
	return out
}
'''
    s += helper
    # apply merge after bcut and whisper in Call
    s = s.replace(
        '''	result, err := t.transcribeViaBcut(ctx, filePath)
	if err != nil || result == nil || len(result.Segments) == 0 {''',
        '''	result, err := t.transcribeViaBcut(ctx, filePath)
	if err != nil || result == nil || len(result.Segments) == 0 {''',
    )
    # after successful result, merge
    s = s.replace(
        '''	// 6. 保存 SRT 字幕文件
	if len(result.Segments) > 0 {''',
        '''	if result != nil && len(result.Segments) > 0 {
		before := len(result.Segments)
		result.Segments = MergeTranscriptSegments(result.Segments, 12)
		t.logger.Info("Merged transcript segments", zap.Int("before", before), zap.Int("after", len(result.Segments)))
	}

	// 6. 保存 SRT 字幕文件
	if len(result.Segments) > 0 {''',
    )
p.write_text(s)
print("bcut merge helper added")
