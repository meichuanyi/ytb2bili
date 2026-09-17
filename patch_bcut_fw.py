from pathlib import Path
p = Path("/root/projects/ytb2bili-main/pkg/tools/bcut_transcriber.go")
s = p.read_text()
# add imports if needed
if "os/exec" not in s:
    s = s.replace('import (\n\t"bytes"\n', 'import (\n\t"bytes"\n\t"os/exec"\n')
if "path/filepath" not in s:
    s = s.replace('\t"net/http"\n', '\t"net/http"\n\t"path/filepath"\n')

old = '''	result, err := t.queryResult(ctx, taskID)
	if err != nil {
		return "", fmt.Errorf("query result failed: %w", err)
	}'''
new = '''	result, err := t.queryResult(ctx, taskID)
	if err != nil {
		t.logger.Warn("Bcut query failed, falling back to local whisper", zap.Error(err))
		result, err = t.transcribeLocalWhisper(ctx, filePath)
		if err != nil {
			return "", fmt.Errorf("query result failed: %w", err)
		}
	}'''
if old not in s:
    raise SystemExit("queryResult block not found")
s = s.replace(old, new, 1)

# append local whisper method before saveSRT or at end of file
if "transcribeLocalWhisper" not in s.split("func (t *BcutTranscriberTool) transcribeLocalWhisper")[0] or "func (t *BcutTranscriberTool) transcribeLocalWhisper" not in s:
    method = '''
// transcribeLocalWhisper 本地 faster-whisper 兜底转写（Bcut 被 412 时）。
func (t *BcutTranscriberTool) transcribeLocalWhisper(ctx context.Context, audioPath string) (*TranscriptResult, error) {
	if strings.TrimSpace(audioPath) == "" {
		return nil, fmt.Errorf("empty audio path")
	}
	if _, err := os.Stat(audioPath); err != nil {
		return nil, fmt.Errorf("audio not found: %w", err)
	}
	outJSON := filepath.Join(os.TempDir(), fmt.Sprintf("whisper_%d.json", time.Now().UnixNano()))
	script := "/root/projects/ytb2bili-main/tools/whisper_transcribe.py"
	py := "/root/projects/gpt-sovits-infer/venv/bin/python"
	if _, err := os.Stat(script); err != nil {
		return nil, fmt.Errorf("whisper script missing: %w", err)
	}
	cmd := exec.CommandContext(ctx, py, script, audioPath, outJSON)
	cmd.Env = append(os.Environ(), "HF_ENDPOINT=https://hf-mirror.com", "PYTHONUNBUFFERED=1")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("local whisper failed: %w: %s", err, string(out[len(out)-min(len(out), 400):]))
	}
	defer os.Remove(outJSON)
	data, err := os.ReadFile(outJSON)
	if err != nil {
		return nil, fmt.Errorf("read whisper output: %w", err)
	}
	var res TranscriptResult
	if err := json.Unmarshal(data, &res); err != nil {
		return nil, fmt.Errorf("parse whisper output: %w", err)
	}
	if res.Language == "" {
		res.Language = "en"
	}
	t.logger.Info("Local whisper transcription finished",
		zap.Int("segments", len(res.Segments)),
		zap.String("language", res.Language))
	return &res, nil
}
'''
    # insert before saveSRT function
    idx = s.find("func (t *BcutTranscriberTool) saveSRT")
    if idx < 0:
        s = s + method
    else:
        s = s[:idx] + method + "\n" + s[idx:]
p.write_text(s)
print("patched bcut whisper fallback")
