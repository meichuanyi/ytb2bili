from pathlib import Path

# 1) LLMTranslate: no transcript -> hard fail + notify
p = Path("/root/projects/ytb2bili-main/internal/workflow/llm_translate_step.go")
s = p.read_text()
old = '''	segments := collectTranscriptTextSegments(vctx.Transcript)
	if len(segments) == 0 {
		vctx.TranslationSkipped = true
		s.logger.Warn("No transcript available, skipping LLM subtitle translation")
		return vctx, nil
	}'''
new = '''	segments := collectTranscriptTextSegments(vctx.Transcript)
	if len(segments) == 0 {
		vctx.TranslationSkipped = true
		s.logger.Error("No transcript available for LLM subtitle translation")
		if s.notifier != nil {
			s.notifier.NotifyAsync(ctx, service.NotifyPayload{
				Event:   service.NotifyEventVideoFailed,
				Title:   "字幕翻译失败",
				Message: "原因：没有可用转写文本（Transcribe 失败或字幕为空）。任务已中止，不会继续上传。请检查转写服务后重试。",
				VideoID: vctx.VideoID,
				UserID:  vctx.UserID,
				Status:  "no_transcript",
			})
		}
		return nil, fmt.Errorf("字幕翻译失败: 没有可用转写文本")
	}'''
if old not in s:
    print("no-transcript block missing")
else:
    s = s.replace(old, new, 1)
    p.write_text(s)
    print("no-transcript hard fail")

# 2) CronJob notify
p = Path("/root/projects/ytb2bili-main/internal/background/cron_job.go")
s = p.read_text()
if "notifier" not in s:
    # add field to struct - find type CronJob struct
    import re
    m = re.search(r"type CronJob struct \{", s)
    if m:
        s = s.replace("type CronJob struct {", "type CronJob struct {\n\tnotifier *service.Notifier", 1)
        print("cron struct field")
    # find constructor NewCronJob params
    if "NewCronJob" in s:
        # add optional notifier to params struct if exists
        s = s.replace("Notifier *service.Notifier", "Notifier *service.Notifier")  # no-op
        # inject via params if fx.In
        if "fx.In" in s and "Notifier *service.Notifier" not in s:
            # add to first fx.In struct near CronJob
            s = s.replace("fx.In\n", "fx.In\n\tNotifier *service.Notifier `optional:\"true\"`\n", 1)
            print("fx.In notifier")
        # assignment in constructor
        s = re.sub(r"return &CronJob\{", "return &CronJob{\n\t\tnotifier: notifier,", s, count=1)
        # if uses params struct
        s = re.sub(r"j := &CronJob\{", "j := &CronJob{\n\t\tnotifier: params.Notifier,", s, count=1)

# fail notify
old = '''		if err != nil {
			logger.Error("视频处理失败",
				zap.Error(err),
				zap.Int("retry_count", video.RetryCount+1),
			)
'''
new = '''		if err != nil {
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
'''
if old in s and "视频处理失败" in new:
    if "j.notifier.NotifyAsync" not in s:
        s = s.replace(old, new, 1)
        print("cron fail notify")

# success notify - find videoUpdates after process success
if "j.notifier.NotifyAsync" in s or "notifier" in s:
    # find ProcessContextWithTracking success path
    idx = s.find('vctx, err := j.youtubeChain.ProcessContextWithTracking')
    # after err check return, add success notify near videoUpdates
    marker = 'videoUpdates := map[string]interface{}{'
    if marker in s and 'NotifyEventVideoCompleted' not in s:
        s = s.replace(marker, '''if j.notifier != nil {
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

	videoUpdates := map[string]interface{}{''', 1)
        print("cron success notify")

# imports
if "internal/service" not in s:
    s = s.replace('"github.com/difyz9/ytb2bili/internal/handler"', '"github.com/difyz9/ytb2bili/internal/handler"\n\t"github.com/difyz9/ytb2bili/internal/service"', 1)
if '"fmt"' not in s:
    s = s.replace('import (\n', 'import (\n\t"fmt"\n', 1)
p.write_text(s)
print("cron_job written")
