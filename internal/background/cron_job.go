package background

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/difyz9/ytb2bili/internal/analytics"
	"github.com/difyz9/ytb2bili/internal/handler"
	"github.com/difyz9/ytb2bili/internal/service"
	"github.com/difyz9/ytb2bili/internal/workflow"
	biliaccount "github.com/difyz9/ytb2bili/pkg/bilibili"
	"github.com/difyz9/ytb2bili/pkg/store/model"
	"github.com/gin-gonic/gin"
	"go.uber.org/fx"
	"go.uber.org/zap"
	"gorm.io/gorm"
)

const (
	maxCronConcurrency                     = 3
	maxCronRetryCount                      = 2
	biliAutoUploadScanInterval             = 1 * time.Minute
	maxAutoUploadVideosPerUser             = 5
	biliSubtitleScanInterval               = 5 * time.Minute
	maxSubtitleUploadVideosPerBatch        = 10
	youTubeFeedSyncSettingsRefreshInterval = 1 * time.Minute
)

// CronJob owns background polling and scheduled processing that does not
// belong to the HTTP handler boundary.
type CronJob struct {
	notifier                *service.Notifier
	logger                  *zap.Logger
	db                      *gorm.DB
	userSettings            *service.UserSettingsClient
	systemSettings          *service.SystemSettingsClient
	youtubeChain            *workflow.YouTubeChain
	youtubeHandler          *handler.YouTubeHandler
	biliChain               *workflow.BilibiliChain
	accountService          *biliaccount.Service
	analytics               *analytics.Client
	ticker                  *time.Ticker
	biliTicker              *time.Ticker
	subtitleTicker          *time.Ticker
	stopChan                chan struct{}
	semaphore               chan struct{}
	wg                      sync.WaitGroup
	statusMu                sync.RWMutex
	started                 bool
	startedAt               time.Time
	lastVideoPollAt         time.Time
	lastVideoPollFinishedAt time.Time
	lastPendingCount        int
	lastVideoPollError      string
}

type StatusResponse struct {
	Started                  bool       `json:"started"`
	StartedAt                *time.Time `json:"started_at,omitempty"`
	VideoPollIntervalSeconds int        `json:"video_poll_interval_seconds"`
	LastVideoPollAt          *time.Time `json:"last_video_poll_at,omitempty"`
	LastVideoPollFinishedAt  *time.Time `json:"last_video_poll_finished_at,omitempty"`
	LastPendingCount         int        `json:"last_pending_count"`
	LastVideoPollError       string     `json:"last_video_poll_error,omitempty"`
	ActiveWorkers            int        `json:"active_workers"`
	MaxConcurrency           int        `json:"max_concurrency"`
	PendingRetryLimit        int        `json:"pending_retry_limit"`
}

type CronJobParams struct {
	fx.In
	Notifier       *service.Notifier `optional:"true"`
	Logger         *zap.Logger
	DB             *gorm.DB
	UserSettings   *service.UserSettingsClient
	SystemSettings *service.SystemSettingsClient
	YoutubeChain   *workflow.YouTubeChain
	YoutubeHandler *handler.YouTubeHandler
	BiliChain      *workflow.BilibiliChain
	AccountService *biliaccount.Service
	Analytics      *analytics.Client
	Lifecycle      fx.Lifecycle
}

func NewCronJob(params CronJobParams) *CronJob {
	job := &CronJob{
		notifier:       params.Notifier,
		logger:         params.Logger,
		db:             params.DB,
		userSettings:   params.UserSettings,
		systemSettings: params.SystemSettings,
		youtubeChain:   params.YoutubeChain,
		youtubeHandler: params.YoutubeHandler,
		biliChain:      params.BiliChain,
		accountService: params.AccountService,
		analytics:      params.Analytics,
		ticker:         time.NewTicker(5 * time.Second),
		biliTicker:     time.NewTicker(biliAutoUploadScanInterval),
		subtitleTicker: time.NewTicker(biliSubtitleScanInterval),
		stopChan:       make(chan struct{}),
		semaphore:      make(chan struct{}, maxCronConcurrency),
	}

	params.Lifecycle.Append(fx.Hook{
		OnStart: func(ctx context.Context) error {
			job.markStarted()
			job.logger.Info("启动视频处理定时任务（每5秒检查一次）")
			job.logger.Info("启动YouTube feed同步定时任务（按系统设置执行）")
			job.logger.Info("启动B站自动上传定时任务（每分钟扫描一次，按用户配置间隔执行）")
			job.logger.Info("启动B站字幕上传定时任务（每5分钟扫描一次审核通过的视频）")
			go job.startVideoProcessingJob()
			go job.startFailedRetryJob()
			go job.startBilibiliSubtitleUploadJob()
			go job.startYouTubeFeedSync()
			return nil
		},
		OnStop: func(ctx context.Context) error {
			job.logger.Info("停止定时任务")
			job.markStopped()
			close(job.stopChan)
			job.ticker.Stop()
			job.biliTicker.Stop()
			job.subtitleTicker.Stop()
			job.wg.Wait()
			return nil
		},
	})

	return job
}

func (j *CronJob) startVideoProcessingJob() {
	for {
		select {
		case <-j.ticker.C:
			j.processVideos()
		case <-j.stopChan:
			j.logger.Info("视频处理任务已停止")
			return
		}
	}
}

func (j *CronJob) startYouTubeFeedSync() {
	var lastSyncAt time.Time
	wasEnabled := false

	for {
		enabled, interval := j.loadYouTubeFeedSyncSchedule()
		if enabled && !wasEnabled {
			lastSyncAt = time.Time{}
		}
		wasEnabled = enabled

		if !enabled {
			if !j.waitForYouTubeFeedSync(youTubeFeedSyncSettingsRefreshInterval) {
				j.logger.Info("YouTube feed同步任务已停止")
				return
			}
			continue
		}

		if lastSyncAt.IsZero() || time.Since(lastSyncAt) >= interval {
			j.logger.Info("YouTube feed同步开始", zap.Int("interval_minutes", int(interval.Minutes())))
			j.youtubeHandler.SyncYouTubeFeed()
			lastSyncAt = time.Now()
			continue
		}

		remaining := interval - time.Since(lastSyncAt)
		waitDuration := remaining
		if waitDuration > youTubeFeedSyncSettingsRefreshInterval {
			waitDuration = youTubeFeedSyncSettingsRefreshInterval
		}
		if !j.waitForYouTubeFeedSync(waitDuration) {
			j.logger.Info("YouTube feed同步任务已停止")
			return
		}
	}
}

func (j *CronJob) loadYouTubeFeedSyncSchedule() (bool, time.Duration) {
	intervalMinutes := model.DefaultYouTubeFeedSyncIntervalMinutes
	enabled := true

	if j.systemSettings == nil || !j.systemSettings.IsEnabled() {
		return enabled, time.Duration(intervalMinutes) * time.Minute
	}

	settings, err := j.systemSettings.GetSettings(context.Background())
	if err != nil {
		j.logger.Warn("读取YouTube feed同步系统设置失败，使用默认值", zap.Error(err))
		return enabled, time.Duration(intervalMinutes) * time.Minute
	}

	if value := settings[model.SystemSettingKeyYouTubeFeedSyncEnabled]; value == "0" || value == "false" {
		enabled = false
	}
	if value := settings[model.SystemSettingKeyYouTubeFeedSyncInterval]; value != "" {
		if minutes, err := strconv.Atoi(value); err == nil {
			intervalMinutes = model.NormalizeYouTubeFeedSyncIntervalMinutes(minutes)
		}
	}

	return enabled, time.Duration(intervalMinutes) * time.Minute
}

func (j *CronJob) waitForYouTubeFeedSync(duration time.Duration) bool {
	timer := time.NewTimer(duration)
	defer timer.Stop()

	select {
	case <-timer.C:
		return true
	case <-j.stopChan:
		return false
	}
}

func (j *CronJob) processVideos() {
	j.requeueFailedVideos()
	ctx := context.Background()
	j.markVideoPollStarted()
	defer j.markVideoPollFinished()

	// 将订阅自动同步（synced）的新视频自动提升为待处理（pending），
	// 打通「频道更新→下载处理→自动上传B站」的无人值守链路。
	// synced 记录仅由 feed 同步为 active 订阅创建；停订（inactive）后不会再产生新记录。
	if err := j.db.Model(&model.Video{}).
		Where("status = ?", "synced").
		Update("status", model.VideoStatusPending).Error; err != nil {
		j.logger.Error("提升订阅同步视频为待处理失败", zap.Error(err))
	}

	var videos []model.Video
	err := j.db.Where("status = ? AND retry_count < ?", model.VideoStatusPending, maxCronRetryCount).
		Order("created_at ASC").
		Limit(10).
		Find(&videos).Error
	if err != nil {
		j.recordVideoPollResult(0, err)
		j.logger.Error("查询待处理视频失败", zap.Error(err))
		return
	}
	j.recordVideoPollResult(len(videos), nil)

	if len(videos) == 0 {
		return
	}

	j.logger.Info("发现待处理视频", zap.Int("count", len(videos)))

	for _, video := range videos {
		j.semaphore <- struct{}{}
		j.wg.Add(1)
		go func(v model.Video) {
			defer func() {
				j.wg.Done()
				<-j.semaphore
			}()
			j.processVideo(ctx, v)
		}(video)
	}
}

func (j *CronJob) markStarted() {
	j.statusMu.Lock()
	defer j.statusMu.Unlock()
	j.started = true
	j.startedAt = time.Now()
}

func (j *CronJob) markStopped() {
	j.statusMu.Lock()
	defer j.statusMu.Unlock()
	j.started = false
}

func (j *CronJob) markVideoPollStarted() {
	j.statusMu.Lock()
	defer j.statusMu.Unlock()
	j.lastVideoPollAt = time.Now()
}

func (j *CronJob) markVideoPollFinished() {
	j.statusMu.Lock()
	defer j.statusMu.Unlock()
	j.lastVideoPollFinishedAt = time.Now()
}

func (j *CronJob) recordVideoPollResult(pendingCount int, err error) {
	j.statusMu.Lock()
	defer j.statusMu.Unlock()
	j.lastPendingCount = pendingCount
	if err != nil {
		j.lastVideoPollError = err.Error()
		return
	}
	j.lastVideoPollError = ""
}

func (j *CronJob) Snapshot() StatusResponse {
	j.statusMu.RLock()
	defer j.statusMu.RUnlock()

	return StatusResponse{
		Started:                  j.started,
		StartedAt:                cloneTimePtr(j.startedAt),
		VideoPollIntervalSeconds: int((5 * time.Second).Seconds()),
		LastVideoPollAt:          cloneTimePtr(j.lastVideoPollAt),
		LastVideoPollFinishedAt:  cloneTimePtr(j.lastVideoPollFinishedAt),
		LastPendingCount:         j.lastPendingCount,
		LastVideoPollError:       j.lastVideoPollError,
		ActiveWorkers:            len(j.semaphore),
		MaxConcurrency:           maxCronConcurrency,
		PendingRetryLimit:        maxCronRetryCount,
	}
}

func cloneTimePtr(value time.Time) *time.Time {
	if value.IsZero() {
		return nil
	}
	copyValue := value
	return &copyValue
}

func (j *CronJob) StatusHandler(c *gin.Context) {
	handler.Success(c, j.Snapshot())
}

func (j *CronJob) processVideo(ctx context.Context, video model.Video) {
	logger := j.logger.With(
		zap.String("video_id", video.VideoID),
		zap.Uint("id", video.ID),
	)

	logger.Info("开始处理视频", zap.Int("retry_count", video.RetryCount))

	updates := map[string]interface{}{
		"status":      model.VideoStatusProcessing,
		"retry_count": video.RetryCount + 1,
	}
	if err := j.db.Model(&video).Updates(updates).Error; err != nil {
		logger.Error("更新视频状态为002（处理中）失败", zap.Error(err))
		return
	}

	preferences := handler.ResolveVideoProcessingPreferences(
		ctx,
		j.userSettings,
		video.UserID,
		video.PreferredResolution,
		handler.ParseStoredTaskChainSettings(video.TaskChainSettings),
		handler.BuildSpeechSynthesisConfigFromVoiceName(video.SpeechVoiceName),
	)

	initialCtx := &workflow.VideoContext{
		VideoURL:              video.URL,
		VideoID:               video.VideoID,
		UserID:                video.UserID,
		PreferredResolution:   preferences.PreferredResolution,
		SpeechSynthesisConfig: preferences.SpeechSynthesisConfig,
		TaskChainSettings:     preferences.TaskChainSettings,
	}

	vctx, err := j.youtubeChain.ProcessContextWithTracking(ctx, initialCtx, video.VideoID, video.UserID)
	if err != nil {
		logger.Error("视频处理失败",
			zap.Error(err),
			zap.Int("retry_count", video.RetryCount+1),
		)

		if j.notifier != nil {
			j.notifier.NotifyAsync(ctx, service.NotifyPayload{
				Event:   service.NotifyEventVideoFailed,
				Title:   "视频处理失败",
				Message: fmt.Sprintf("原因：%v", err),
				VideoID: video.VideoID,
				UserID:  video.UserID,
				Status:  "failed",
			})
		}

		if video.RetryCount+1 >= maxCronRetryCount {
			if err := j.db.Model(&video).Update("status", model.VideoStatusFailed).Error; err != nil {
				logger.Error("更新视频状态为004（失败）失败", zap.Error(err))
			}
			logger.Warn("视频处理失败次数超过限制，标记为失败",
				zap.Int("max_retry", maxCronRetryCount),
			)
			if j.notifier != nil {
				j.notifier.NotifyAsync(ctx, service.NotifyPayload{
					Event:   service.NotifyEventVideoFailed,
					Title:   "处理失败，已停止自动重试",
					Message: fmt.Sprintf("视频「%s」已重试 %d 次仍失败，自动重跑已停止。\n原因：%v\n请手动处理后重试。", video.Title, video.RetryCount+1, err),
					VideoID: video.VideoID,
					UserID:  video.UserID,
					Status:  "retry_exhausted",
				})
			}
		} else {
			if err := j.db.Model(&video).Update("status", model.VideoStatusPending).Error; err != nil {
				logger.Error("恢复视频状态为001（待处理）失败", zap.Error(err))
			}
			logger.Info("视频将在下次检查时重试",
				zap.Int("current_retry", video.RetryCount+1),
				zap.Int("max_retry", maxCronRetryCount),
			)
		}
		return
	}

	if j.notifier != nil {
		title := vctx.Title
		if title == "" {
			title = video.Title
		}
		status := "completed"
		evt := service.NotifyEventVideoCompleted
		nt := "视频处理完成"
		msg := title
		if vctx != nil && vctx.TranslationSkipped {
			evt = service.NotifyEventVideoWarning
			nt = "视频处理完成（无中文字幕）"
			msg = title + "：翻译/字幕未生成。"
			status = "completed_without_zh"
		}
		j.notifier.NotifyAsync(ctx, service.NotifyPayload{
			Event: evt, Title: nt, Message: msg,
			VideoID: video.VideoID, UserID: video.UserID, Status: status,
			Extra: map[string]string{"path": vctx.VideoPath},
		})
	}

	videoUpdates := map[string]interface{}{
		"status":          model.VideoStatusCompleted,
		"video_path":      vctx.VideoPath,
		"subtitle_path":   vctx.AudioPath,
		"generated_title": vctx.Title,
		"generated_desc":  vctx.Description,
		"generated_tags":  vctx.Tags,
		"bili_bvid":       vctx.BiliBVID,
		"bili_aid":        vctx.BiliAID,
	}

	if err := j.db.Model(&video).Updates(videoUpdates).Error; err != nil {
		logger.Error("更新视频处理结果失败", zap.Error(err))
		return
	}

	logger.Info("视频处理完成",
		zap.String("title", vctx.Title),
		zap.String("bili_bvid", vctx.BiliBVID),
	)
}

func (j *CronJob) startFailedRetryJob() {
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
}

// requeueFailedVideos 将达到失败状态的视频重新排队，供后续自动重跑。
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
			"status":    model.VideoStatusPending,
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

func (j *CronJob) uploadPendingVideosToBilibili() {
	// 自动上传已禁用：仅手动上传 / 手动 resume 后的 UploadToBilibili 步骤。
	j.logger.Debug("跳过 B 站自动上传（已改为失败任务自动重跑）")
	return
	now := time.Now()
	var userSettings []model.UserSettings
	err := j.db.Where("auto_upload_enabled = ?", true).Find(&userSettings).Error
	if err != nil {
		j.logger.Error("查询自动上传用户配置失败", zap.Error(err))
		return
	}
	if len(userSettings) == 0 {
		return
	}

	for _, settings := range userSettings {
		if !j.shouldRunBilibiliAutoUpload(now, settings) {
			continue
		}
		j.runBilibiliAutoUploadForUser(now, settings)
	}
}

func (j *CronJob) shouldRunBilibiliAutoUpload(now time.Time, settings model.UserSettings) bool {
	interval := time.Duration(model.NormalizeAutoUploadIntervalMinutes(settings.AutoUploadIntervalMinutes)) * time.Minute
	if settings.LastAutoUploadAt == nil {
		return true
	}
	return now.Sub(*settings.LastAutoUploadAt) >= interval
}

func (j *CronJob) runBilibiliAutoUploadForUser(now time.Time, settings model.UserSettings) {
	logger := j.logger.With(
		zap.String("user_id", settings.UserID),
		zap.Int("interval_minutes", model.NormalizeAutoUploadIntervalMinutes(settings.AutoUploadIntervalMinutes)),
	)
	if settings.UserID == "" {
		return
	}
	if j.biliChain == nil {
		logger.Warn("BilibiliChain 未配置，跳过自动上传")
		return
	}
	if err := j.db.Model(&model.UserSettings{}).
		Where("id = ?", settings.ID).
		Update("last_auto_upload_at", now).Error; err != nil {
		logger.Error("更新自动上传调度时间失败", zap.Error(err))
		return
	}

	var videos []model.Video
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
}

func (j *CronJob) startBilibiliSubtitleUploadJob() {
	time.Sleep(30 * time.Second)
	for {
		select {
		case <-j.subtitleTicker.C:
			j.uploadBiliSubtitleForApprovedVideos()
		case <-j.stopChan:
			j.logger.Info("B站字幕上传任务已停止")
			return
		}
	}
}

func (j *CronJob) uploadBiliSubtitleForApprovedVideos() {
	if j.accountService == nil {
		return
	}

	var videos []model.Video
	err := j.db.
		Where("bili_bvid != '' AND bili_bvid IS NOT NULL AND video_path != ''").
		Where(`
			NOT EXISTS (
				SELECT 1 FROM tb_bili_subtitle_uploads s
				WHERE s.video_id = tb_videos.video_id
			)
			OR EXISTS (
				SELECT 1 FROM tb_bili_subtitle_uploads s
				WHERE s.video_id = tb_videos.video_id
				AND s.status IN (?, ?)
			)
		`, model.BiliSubtitleStatusPending, model.BiliSubtitleStatusFailed).
		Order("updated_at ASC").
		Limit(maxSubtitleUploadVideosPerBatch).
		Find(&videos).Error
	if err != nil {
		j.logger.Error("查询待字幕上传B站视频失败", zap.Error(err))
		return
	}
	if len(videos) == 0 {
		return
	}

	j.logger.Info("扫描待字幕上传视频", zap.Int("count", len(videos)))

	for _, video := range videos {
		v := video
		if err := j.accountService.UploadApprovedVideoSubtitles(v); err != nil {
			j.logger.Debug("B站字幕上传本轮结束", zap.String("video_id", v.VideoID), zap.Error(err))
		}
	}
}
