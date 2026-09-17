from pathlib import Path
p = Path("internal/handler/video_process_handler.go")
s = p.read_text()

# add notifier field
if "notifier" not in s:
    # find struct
    if "type VideoProcessHandler struct {" in s:
        s = s.replace(
            "type VideoProcessHandler struct {",
            "type VideoProcessHandler struct {\n\tnotifier   *service.Notifier",
            1,
        )
        print("struct field added")
    # constructor - search for return &VideoProcessHandler
    if "return &VideoProcessHandler{" in s:
        s = s.replace(
            "return &VideoProcessHandler{",
            "return &VideoProcessHandler{\n\t\tnotifier:   notifier,",
            1,
        )
        print("ctor return patched")
        # add param to NewVideoProcessHandler
        import re
        s = re.sub(
            r"func NewVideoProcessHandler\(([^)]*)\)",
            lambda m: f"func NewVideoProcessHandler({m.group(1)}, notifier *service.Notifier)",
            s,
            count=1,
        )
        print("ctor signature patched")
else:
    print("already has notifier")

# hook complete/fail after MarkStatus failed and UpdateProcessingResult completed
old_fail = '''		h.videoService.MarkStatus(c.Request.Context(), videoID, model.VideoStatusFailed)
		c.JSON(http.StatusInternalServerError, VideoProcessResponse{Success: false, Message: "视频处理失败: " + err.Error()})
		return
	}

	// Save results to DB
	updates := map[string]interface{}{
		"platform": platform, "title": result.Title, "description": result.Description,
		"status": model.VideoStatusCompleted, "video_path": result.VideoPath,
	}'''
new_fail = '''		h.videoService.MarkStatus(c.Request.Context(), videoID, model.VideoStatusFailed)
		if h.notifier != nil {
			h.notifier.NotifyAsync(c.Request.Context(), service.NotifyPayload{
				Event: service.NotifyEventVideoFailed, Title: "视频处理失败",
				Message: err.Error(), VideoID: videoID, UserID: req.UserID, Status: model.VideoStatusFailed,
			})
		}
		c.JSON(http.StatusInternalServerError, VideoProcessResponse{Success: false, Message: "视频处理失败: " + err.Error()})
		return
	}

	// Save results to DB
	updates := map[string]interface{}{
		"platform": platform, "title": result.Title, "description": result.Description,
		"status": model.VideoStatusCompleted, "video_path": result.VideoPath,
	}'''
if old_fail in s:
    s = s.replace(old_fail, new_fail, 1)
    print("remote fail hook")
else:
    print("remote fail hook NOT found")

old_ok = '''	h.videoService.UpdateProcessingResult(c.Request.Context(), result.VideoID, updates)

	c.JSON(http.StatusOK, VideoProcessResponse{
		Success: true, Message: "视频处理成功",
		Data: &VideoProcessData{
			VideoID: result.VideoID, VideoPath: result.VideoPath,'''
new_ok = '''	h.videoService.UpdateProcessingResult(c.Request.Context(), result.VideoID, updates)
	if h.notifier != nil {
		title := result.Title
		if title == "" {
			title = result.VideoID
		}
		h.notifier.NotifyAsync(c.Request.Context(), service.NotifyPayload{
			Event: service.NotifyEventVideoCompleted, Title: "视频处理完成",
			Message: title, VideoID: result.VideoID, UserID: req.UserID, Status: model.VideoStatusCompleted,
			Extra: map[string]string{"path": result.VideoPath},
		})
	}

	c.JSON(http.StatusOK, VideoProcessResponse{
		Success: true, Message: "视频处理成功",
		Data: &VideoProcessData{
			VideoID: result.VideoID, VideoPath: result.VideoPath,'''
if old_ok in s:
    s = s.replace(old_ok, new_ok, 1)
    print("remote ok hook")
else:
    print("remote ok hook NOT found")

# local video fail hook
old_local_fail = '''	if err != nil {
		h.videoService.MarkStatus(c.Request.Context(), videoID, model.VideoStatusFailed)
		c.JSON(http.StatusInternalServerError, VideoProcessResponse{Success: false, Message: "视频处理失败: " + err.Error()})
		return
	}

	updates := map[string]interface{}{"status": model.VideoStatusCompleted, "video_path": result.VideoPath}'''
new_local_fail = '''	if err != nil {
		h.videoService.MarkStatus(c.Request.Context(), videoID, model.VideoStatusFailed)
		if h.notifier != nil {
			h.notifier.NotifyAsync(c.Request.Context(), service.NotifyPayload{
				Event: service.NotifyEventVideoFailed, Title: "本地视频处理失败",
				Message: err.Error(), VideoID: videoID, UserID: req.UserID, Status: model.VideoStatusFailed,
			})
		}
		c.JSON(http.StatusInternalServerError, VideoProcessResponse{Success: false, Message: "视频处理失败: " + err.Error()})
		return
	}

	updates := map[string]interface{}{"status": model.VideoStatusCompleted, "video_path": result.VideoPath}'''
if old_local_fail in s:
    s = s.replace(old_local_fail, new_local_fail, 1)
    print("local fail hook")
else:
    print("local fail hook NOT found")

p.write_text(s)
print("handler written, has service import", '"github.com/difyz9/ytb2bili/internal/service"' in s or "internal/service" in s)
