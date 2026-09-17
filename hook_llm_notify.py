from pathlib import Path

# Add notify event constant
p = Path("internal/service/notifier.go")
s = p.read_text()
if "NotifyEventVideoWarning" not in s:
    s = s.replace(
        "\tNotifyEventBilibiliUploaded = \"bilibili.uploaded\"\n)",
        "\tNotifyEventBilibiliUploaded = \"bilibili.uploaded\"\n\tNotifyEventVideoWarning    = \"video.warning\"\n)",
    )
    p.write_text(s)
    print("notifier events")

# Hook LLM translate failure
p = Path("internal/workflow/llm_translate_step.go")
s = p.read_text()
if "notifier" not in s:
    # struct
    s = s.replace(
        "\tTranslator *tools.BatchTranslator `optional:\"true\"`",
        "\tTranslator *tools.BatchTranslator `optional:\"true\"`\n\tnotifier   *service.Notifier          `optional:\"true\"`",
    )
    # find constructor NewLLMTranslateStep
    import re
    # add field assignment if return struct exists
    if "return &LLMTranslateStep{" in s:
        s = s.replace("return &LLMTranslateStep{", "return &LLMTranslateStep{\n\t\tnotifier:   notifier,", 1)
    # signature: add notifier param - look for function
    m = re.search(r"func NewLLMTranslateStep\(([^)]*)\)", s)
    if m:
        args = m.group(1)
        if "notifier" not in args:
            s = s.replace(f"func NewLLMTranslateStep({args})", f"func NewLLMTranslateStep({args}, notifier *service.Notifier)", 1)
            print("ctor patched", args[-80:])
    # notify on translate fail
    s = s.replace(
        '''	if err != nil {
		s.logger.Error("LLM subtitle translation failed", zap.Error(err))
		return vctx, &StepSkippedError{
			Step: s.Name(), Cause: err, Output: vctx,
		}
	}''',
        '''	if err != nil {
		s.logger.Error("LLM subtitle translation failed", zap.Error(err))
		if s.notifier != nil {
			s.notifier.NotifyAsync(ctx, service.NotifyPayload{
				Event:   service.NotifyEventVideoWarning,
				Title:   "字幕翻译失败",
				Message: fmt.Sprintf("LLM 翻译出错：%v。任务将继续，但可能没有中文字幕/配音。", err),
				VideoID: vctx.VideoID,
				UserID:  vctx.UserID,
				Status:  "translate_failed",
			})
		}
		return vctx, &StepSkippedError{
			Step: s.Name(), Cause: err, Output: vctx,
		}
	}''',
    )
    # ensure service import
    if "internal/service" not in s:
        s = s.replace('"github.com/difyz9/ytb2bili/internal/config"', '"github.com/difyz9/ytb2bili/internal/config"\n\t"github.com/difyz9/ytb2bili/internal/service"', 1)
    # fmt import
    if '"fmt"' not in s:
        s = s.replace('import (\n', 'import (\n\t"fmt"\n', 1)
    p.write_text(s)
    print("llm_translate patched")
else:
    print("llm_translate already has notifier")

# Also notify when pipeline done but translation skipped in video process handler
p = Path("internal/handler/video_process_handler.go")
s = p.read_text()
if "TranslationSkipped" not in s:
    old = '''	if h.notifier != nil {
		title := result.Title
		if title == "" {
			title = result.VideoID
		}
		h.notifier.NotifyAsync(c.Request.Context(), service.NotifyPayload{
			Event: service.NotifyEventVideoCompleted, Title: "视频处理完成",
			Message: title, VideoID: result.VideoID, UserID: req.UserID, Status: model.VideoStatusCompleted,
			Extra: map[string]string{"path": result.VideoPath},
		})
	}'''
    new = '''	if h.notifier != nil {
		title := result.Title
		if title == "" {
			title = result.VideoID
		}
		status := model.VideoStatusCompleted
		evt := service.NotifyEventVideoCompleted
		nt := "视频处理完成"
		msg := title
		if result != nil && result.TranslationSkipped {
			evt = service.NotifyEventVideoWarning
			nt = "视频处理完成（无中文字幕）"
			msg = title + "：翻译/字幕未生成，请检查 LLM 配置或任务链。"
			status = "completed_without_zh"
		}
		h.notifier.NotifyAsync(c.Request.Context(), service.NotifyPayload{
			Event: evt, Title: nt,
			Message: msg, VideoID: result.VideoID, UserID: req.UserID, Status: status,
			Extra: map[string]string{"path": result.VideoPath},
		})
	}'''
    if old in s:
        s = s.replace(old, new, 1)
        p.write_text(s)
        print("handler complete notify updated")
    else:
        print("handler complete block not found")
else:
    print("handler already checks TranslationSkipped")
