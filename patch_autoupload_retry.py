from pathlib import Path
p = Path("/root/projects/ytb2bili-main/internal/background/cron_job.go")
s = p.read_text()

# 1) more retries for processing
s = s.replace("maxCronRetryCount                      = 3", "maxCronRetryCount                      = 8")

# 2) quality gate on auto upload
old = '''	var videos []model.Video
	err := j.db.
		Where("user_id = ? AND status = ? AND video_path != '' AND (bili_bvid = '' OR bili_bvid IS NULL)", settings.UserID, model.VideoStatusCompleted).
		Order("updated_at ASC").
		Limit(maxAutoUploadVideosPerUser).
		Find(&videos).Error
	if err != nil {
		logger.Error("查询用户待上传B站视频失败", zap.Error(err))
		return
	}
	if len(videos) == 0 {
		return
	}

	logger.Info("开始按用户配置自动上传B站视频", zap.Int("count", len(videos)))
	ctx := context.Background()
	for _, video := range videos {
		v := video
		videoLogger := logger.With(zap.String("video_id", v.VideoID), zap.Uint("id", v.ID))
		if _, err := handler.UploadVideoToBilibili(ctx, videoLogger, j.accountService, j.biliChain, j.analytics, settings.UserID, &v, nil); err != nil {
			videoLogger.Error("自动上传B站失败", zap.Error(err))
		}
	}
}'''
new = '''	var videos []model.Video
	err := j.db.
		Where("user_id = ? AND status = ? AND video_path != '' AND (bili_bvid = '' OR bili_bvid IS NULL)", settings.UserID, model.VideoStatusCompleted).
		Order("updated_at ASC").
		Limit(maxAutoUploadVideosPerUser * 3).
		Find(&videos).Error
	if err != nil {
		logger.Error("查询用户待上传B站视频失败", zap.Error(err))
		return
	}

	// 质量门槛：只自动上传「像样」的中配成品，避免空标题/占位简介/无字幕直接上站。
	ready := make([]model.Video, 0, len(videos))
	for _, video := range videos {
		if reason := autoUploadBlockReason(&video); reason != "" {
			logger.Info("跳过自动上传（质量门槛）",
				zap.String("video_id", video.VideoID),
				zap.Uint("id", video.ID),
				zap.String("reason", reason),
				zap.String("title", video.Title),
				zap.String("generated_title", video.GeneratedTitle),
			)
			continue
		}
		ready = append(ready, video)
		if len(ready) >= maxAutoUploadVideosPerUser {
			break
		}
	}
	if len(ready) == 0 {
		return
	}

	logger.Info("开始按用户配置自动上传B站视频", zap.Int("count", len(ready)))
	ctx := context.Background()
	for _, video := range ready {
		v := video
		videoLogger := logger.With(zap.String("video_id", v.VideoID), zap.Uint("id", v.ID))
		if _, err := handler.UploadVideoToBilibili(ctx, videoLogger, j.accountService, j.biliChain, j.analytics, settings.UserID, &v, nil); err != nil {
			videoLogger.Error("自动上传B站失败", zap.Error(err))
		}
	}
}

// autoUploadBlockReason 返回阻止自动上传的原因；空字符串表示允许上传。
func autoUploadBlockReason(v *model.Video) string {
	if v == nil {
		return "video is nil"
	}
	if strings.TrimSpace(v.VideoPath) == "" {
		return "no local video file"
	}
	desc := strings.TrimSpace(v.GeneratedDesc)
	title := strings.TrimSpace(v.GeneratedTitle)
	// 默认占位简介
	if desc == "" || desc == "通过自动化工具上传的视频" {
		return "placeholder or empty description"
	}
	// 仍是英文原题且简介过短，视为未完成中文元数据
	if title != "" && !hasCJK(title) && len([]rune(desc)) < 40 {
		return "likely untranslated metadata"
	}
	// 有中文字幕文件
	zhPath := strings.TrimSuffix(v.SubtitlePath, ".mp3")
	if zhPath != "" {
		for _, cand := range []string{
			zhPath + ".zh.srt",
			strings.TrimSuffix(v.VideoPath, filepath.Ext(v.VideoPath)) + ".zh.srt",
			filepath.Join(filepath.Dir(v.VideoPath), "zh.srt"),
		} {
			if strings.TrimSpace(cand) != "" {
				if _, err := os.Stat(cand); err == nil {
					return ""
				}
			}
		}
	}
	if v.VideoPath != "" {
		base := strings.TrimSuffix(v.VideoPath, filepath.Ext(v.VideoPath))
		if _, err := os.Stat(base + ".zh.srt"); err == nil {
			return ""
		}
		if _, err := os.Stat(filepath.Join(filepath.Dir(v.VideoPath), "zh.srt")); err == nil {
			return ""
		}
	}
	return "missing Chinese subtitle"
}

func hasCJK(s string) bool {
	for _, r := range s {
		if r >= 0x4E00 && r <= 0x9FFF {
			return true
		}
	}
	return false
}'''
if old not in s:
    raise SystemExit("auto upload block not found")
s = s.replace(old, new, 1)

# imports os filepath strings
for imp, after in [('\t"os"\n', '\t"fmt"\n'), ('\t"path/filepath"\n', '\t"os"\n'), ('\t"strings"\n', '\t"os"\n')]:
    pass
if '"os"' not in s:
    s = s.replace('import (\n', 'import (\n\t"os"\n', 1)
if '"path/filepath"' not in s:
    s = s.replace('import (\n', 'import (\n\t"path/filepath"\n', 1)
if '"strings"' not in s:
    s = s.replace('import (\n', 'import (\n\t"strings"\n', 1)

# 3) requeue failed videos for retry
if "requeueFailedVideos" not in s:
    s = s.replace(
        "func (j *CronJob) uploadPendingVideosToBilibili() {",
        '''// requeueFailedVideos 将达到失败状态的视频重新排队，供后续自动重跑。
func (j *CronJob) requeueFailedVideos() {
	// 冷却：updated_at 距今 > 10 分钟，且 retry_count 未超限
	cutoff := time.Now().Add(-10 * time.Minute)
	var videos []model.Video
	err := j.db.
		Where("status = ? AND retry_count < ? AND updated_at < ?", model.VideoStatusFailed, maxCronRetryCount, cutoff).
		Order("updated_at ASC").
		Limit(5).
		Find(&videos).Error
	if err != nil {
		j.logger.Error("查询失败待重跑视频失败", zap.Error(err))
		return
	}
	if len(videos) == 0 {
		return
	}
	for _, video := range videos {
		if err := j.db.Model(&video).Updates(map[string]interface{}{
			"status":   model.VideoStatusPending,
			"error_msg": "auto requeued after failure",
		}).Error; err != nil {
			j.logger.Warn("重排队失败视频失败",
				zap.String("video_id", video.VideoID),
				zap.Error(err))
			continue
		}
		j.logger.Info("失败任务已重新排队，将自动重跑",
			zap.String("video_id", video.VideoID),
			zap.Uint("id", video.ID),
			zap.Int("retry_count", video.RetryCount+1),
			zap.Int("max_retry", maxCronRetryCount),
		)
	}
}

func (j *CronJob) uploadPendingVideosToBilibili() {''',
        1,
    )
    # call requeue before processVideos each poll
    s = s.replace(
        "func (j *CronJob) processVideos() {",
        "func (j *CronJob) processVideos() {\n\tj.requeueFailedVideos()",
        1,
    )
    print("requeue added")

p.write_text(s)
print("cron patched")
