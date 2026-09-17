from pathlib import Path
p = Path("/root/projects/ytb2bili-main/internal/background/cron_job.go")
s = p.read_text()

# 1) replace OnStart auto upload job with failed retry
s = s.replace(
    "go job.startBilibiliAutoUploadJob()",
    "go job.startFailedRetryJob()",
)

# 2) replace startBilibiliAutoUploadJob implementation with failed retry
old_job = '''func (j *CronJob) startBilibiliAutoUploadJob() {
	time.Sleep(10 * time.Second)
	for {
		select {
		case <-j.biliTicker.C:
			j.uploadPendingVideosToBilibili()
		case <-j.stopChan:
			j.logger.Info("B站自动上传任务已停止")
			return
		}
	}
}'''
new_job = '''func (j *CronJob) startFailedRetryJob() {
	time.Sleep(15 * time.Second)
	for {
		select {
		case <-j.biliTicker.C:
			j.retryFailedVideos()
		case <-j.stopChan:
			j.logger.Info("失败任务自动重跑已停止")
			return
		}
	}
}

// retryFailedVideos 将仍可重试的失败视频放回待处理队列。
// 原「自动上传 B 站」已移除：避免空标题/空简介/无字幕内容被直接投稿。
func (j *CronJob) retryFailedVideos() {
	result := j.db.Model(&model.Video{}).
		Where("status = ? AND retry_count < ?", model.VideoStatusFailed, maxCronRetryCount).
		Updates(map[string]interface{}{
			"status": model.VideoStatusPending,
		})
	if result.Error != nil {
		j.logger.Error("失败任务自动重跑失败", zap.Error(result.Error))
		return
	}
	if result.RowsAffected > 0 {
		j.logger.Info("失败任务已放回待处理", zap.Int64("count", result.RowsAffected))
		if j.notifier != nil {
			j.notifier.NotifyAsync(context.Background(), service.NotifyPayload{
				Event:   service.NotifyEventVideoWarning,
				Title:   "失败任务已自动重跑",
				Message: fmt.Sprintf("有 %d 条失败视频已放回队列继续处理。", result.RowsAffected),
				Status:  "auto_retry",
			})
		}
	}
}'''
if old_job not in s:
    raise SystemExit("auto upload job not found")
s = s.replace(old_job, new_job, 1)

# 3) make uploadPendingVideosToBilibili no-op / return early with log (keep function for API manual upload path)
# find function and add early return after signature
old_fn = '''func (j *CronJob) uploadPendingVideosToBilibili() {
	now := time.Now()'''
new_fn = '''func (j *CronJob) uploadPendingVideosToBilibili() {
	// 自动上传已禁用：仅手动上传 / 手动 resume 后的 UploadToBilibili 步骤。
	j.logger.Debug("跳过 B 站自动上传（已改为失败任务自动重跑）")
	return
	now := time.Now()'''
if old_fn not in s:
    print("uploadPendingVideosToBilibili header missing, skip")
else:
    s = s.replace(old_fn, new_fn, 1)
    print("auto upload disabled")

p.write_text(s)
print("cron_job updated")
