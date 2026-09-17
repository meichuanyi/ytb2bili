from pathlib import Path
p = Path("/root/projects/ytb2bili-main/pkg/tools/bcut_transcriber.go")
s = p.read_text()

# Replace Call from "Starting BCut" through queryResult fallback with robust wrapper
old = '''	t.logger.Info("Starting BCut transcription",
		zap.String("file", filePath))

	// 读取文件
	fileData, err := os.ReadFile(filePath)
	if err != nil {
		return "", fmt.Errorf("failed to read file: %w", err)
	}

	// 1. 申请上传
	t.logger.Info("Requesting upload...")
	uploadResp, err := t.requestUpload(ctx, fileData)
	if err != nil {
		return "", fmt.Errorf("request upload failed: %w", err)
	}

	// 2. 分片上传
	t.logger.Info("Uploading file parts...",
		zap.Int("parts", len(uploadResp.Data.UploadURLs)),
		zap.Int("size_kb", uploadResp.Data.Size/1024))
	etags, err := t.uploadParts(ctx, fileData, uploadResp)
	if err != nil {
		return "", fmt.Errorf("upload parts failed: %w", err)
	}

	// 3. 提交上传
	t.logger.Info("Committing upload...")
	downloadURL, err := t.commitUpload(ctx, uploadResp, etags)
	if err != nil {
		return "", fmt.Errorf("commit upload failed: %w", err)
	}

	// 4. 创建转录任务
	t.logger.Info("Creating transcription task...")
	taskID, err := t.createTask(ctx, downloadURL)
	if err != nil {
		return "", fmt.Errorf("create task failed: %w", err)
	}

	// 5. 轮询查询结果
	t.logger.Info("Waiting for transcription result...",
		zap.String("task_id", taskID))
	result, err := t.queryResult(ctx, taskID)
	if err != nil {
		t.logger.Warn("Bcut query failed, falling back to local whisper", zap.Error(err))
		result, err = t.transcribeLocalWhisper(ctx, filePath)
		if err != nil {
			return "", fmt.Errorf("query result failed: %w", err)
		}
	}
'''
new = '''	t.logger.Info("Starting BCut transcription",
		zap.String("file", filePath))

	result, err := t.transcribeViaBcut(ctx, filePath)
	if err != nil || result == nil || len(result.Segments) == 0 {
		reason := err
		if reason == nil {
			reason = fmt.Errorf("bcut returned empty segments")
		}
		t.logger.Warn("Bcut transcription unavailable, falling back to local whisper", zap.Error(reason))
		result, err = t.transcribeLocalWhisper(ctx, filePath)
		if err != nil {
			return "", fmt.Errorf("bcut and local whisper both failed: bcut=%v whisper=%w", reason, err)
		}
	}
'''
if old not in s:
    raise SystemExit("Call body not found")
s = s.replace(old, new, 1)

# add transcribeViaBcut before transcribeLocalWhisper
if "func (t *BcutTranscriberTool) transcribeViaBcut" not in s:
    method = '''
// transcribeViaBcut 执行完整 Bcut 云端转写流程。
func (t *BcutTranscriberTool) transcribeViaBcut(ctx context.Context, filePath string) (*TranscriptResult, error) {
	fileData, err := os.ReadFile(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to read file: %w", err)
	}
	t.logger.Info("Requesting upload...")
	uploadResp, err := t.requestUpload(ctx, fileData)
	if err != nil {
		return nil, fmt.Errorf("request upload failed: %w", err)
	}
	t.logger.Info("Uploading file parts...",
		zap.Int("parts", len(uploadResp.Data.UploadURLs)),
		zap.Int("size_kb", uploadResp.Data.Size/1024))
	etags, err := t.uploadParts(ctx, fileData, uploadResp)
	if err != nil {
		return nil, fmt.Errorf("upload parts failed: %w", err)
	}
	t.logger.Info("Committing upload...")
	downloadURL, err := t.commitUpload(ctx, uploadResp, etags)
	if err != nil {
		return nil, fmt.Errorf("commit upload failed: %w", err)
	}
	t.logger.Info("Creating transcription task...")
	taskID, err := t.createTask(ctx, downloadURL)
	if err != nil {
		return nil, fmt.Errorf("create task failed: %w", err)
	}
	t.logger.Info("Waiting for transcription result...", zap.String("task_id", taskID))
	result, err := t.queryResult(ctx, taskID)
	if err != nil {
		return nil, fmt.Errorf("query result failed: %w", err)
	}
	return result, nil
}
'''
    idx = s.find("func (t *BcutTranscriberTool) transcribeLocalWhisper")
    if idx < 0:
        s = s + method
    else:
        s = s[:idx] + method + "\n" + s[idx:]

p.write_text(s)
print("Call rewritten with full-fallback")
