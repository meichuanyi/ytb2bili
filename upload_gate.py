from pathlib import Path
import re

# 1) cron: max retries = 2 + permanent fail notify
p = Path("/root/projects/ytb2bili-main/internal/background/cron_job.go")
s = p.read_text()
s = s.replace("maxCronRetryCount                      = 8", "maxCronRetryCount                      = 2")
old = '''		if video.RetryCount+1 >= maxCronRetryCount {
			if err := j.db.Model(&video).Update("status", model.VideoStatusFailed).Error; err != nil {
				logger.Error("更新视频状态为004（失败）失败", zap.Error(err))
			}
			logger.Warn("视频处理失败次数超过限制，标记为失败",
				zap.Int("max_retry", maxCronRetryCount),
			)
'''
new = '''		if video.RetryCount+1 >= maxCronRetryCount {
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
					Message: fmt.Sprintf("视频「%s」已重试 %d 次仍失败，自动重跑已停止。\\n原因：%v\\n请手动处理后重试。", video.Title, video.RetryCount+1, err),
					VideoID: video.VideoID,
					UserID:  video.UserID,
					Status:  "retry_exhausted",
				})
			}
'''
if old not in s:
    print("permanent fail block missing")
else:
    s = s.replace(old, new, 1)
    print("permanent fail notify added")
p.write_text(s)

# 2) upload validation helper in workflow package
helper = Path("/root/projects/ytb2bili-main/internal/workflow/upload_quality.go")
helper.write_text('''package workflow

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unicode"
)

const defaultUploadDesc = "通过自动化工具上传的视频"

func containsChinese(s string) bool {
	for _, r := range s {
		if unicode.Is(unicode.Han, r) {
			return true
		}
	}
	return false
}

func hasChineseSubtitleFile(videoPath string) bool {
	if strings.TrimSpace(videoPath) == "" {
		return false
	}
	dir := filepath.Dir(videoPath)
	base := strings.TrimSuffix(filepath.Base(videoPath), filepath.Ext(videoPath))
	candidates := []string{
		filepath.Join(dir, "zh.srt"),
		filepath.Join(dir, base+".zh.srt"),
		filepath.Join(dir, base+".zh-CN.srt"),
		filepath.Join(dir, base+".zh-Hans.srt"),
	}
	matches, _ := filepath.Glob(filepath.Join(dir, "*.zh.srt"))
	candidates = append(candidates, matches...)
	for _, p := range candidates {
		if st, err := os.Stat(p); err == nil && !st.IsDir() && st.Size() > 0 {
			return true
		}
	}
	return false
}

// ValidateChineseUploadReady 上传前校验：必须有中文内容，避免原片直接转载。
func ValidateChineseUploadReady(vctx *VideoContext) error {
	if vctx == nil {
		return fmt.Errorf("上下文为空")
	}
	if vctx.TranslationSkipped {
		return fmt.Errorf("字幕翻译被跳过，禁止上传原片")
	}
	title := strings.TrimSpace(vctx.Title)
	desc := strings.TrimSpace(vctx.Description)
	if desc == defaultUploadDesc {
		return fmt.Errorf("简介仍是默认占位文案，禁止上传")
	}
	if title == "" || !containsChinese(title) {
		return fmt.Errorf("标题缺少中文，疑似未翻译，禁止上传")
	}
	if desc == "" || !containsChinese(desc) {
		return fmt.Errorf("简介缺少中文，疑似未翻译，禁止上传")
	}
	if !hasChineseSubtitleFile(vctx.VideoPath) {
		return fmt.Errorf("未找到中文字幕文件，禁止上传原片")
	}
	return nil
}
''')
print("upload_quality.go written")

# 3) wire validation into UploadToBilibiliStep.Execute
p = Path("/root/projects/ytb2bili-main/internal/workflow/upload_to_bilibili_step.go")
s = p.read_text()
old = '''	s.logger.Info("========================================")
	s.logger.Info("开始上传视频到 Bilibili")
	s.logger.Info("========================================")
'''
new = '''	s.logger.Info("========================================")
	s.logger.Info("开始上传视频到 Bilibili")
	s.logger.Info("========================================")

	if err := ValidateChineseUploadReady(vctx); err != nil {
		s.logger.Error("上传前校验失败，拒绝上传", zap.Error(err))
		return nil, fmt.Errorf("上传前校验失败: %w", err)
	}
'''
if old not in s:
    print("upload execute header missing")
else:
    s = s.replace(old, new, 1)
    print("upload step gated")

# 4) wire into handler UploadVideoToBilibili
p = Path("/root/projects/ytb2bili-main/internal/handler/bilibili_upload_helper.go")
if p.exists():
    s = p.read_text()
    if "ValidateChineseUploadReady" not in s:
        # build a minimal check from model.Video fields
        # insert after video path check
        old = '''	if video.VideoPath == "" {
		return nil, fmt.Errorf("视频文件路径为空，无法上传")
	}
'''
        new = '''	if video.VideoPath == "" {
		return nil, fmt.Errorf("视频文件路径为空，无法上传")
	}
	// 上传前必须确认已翻译出中文，避免原片当转载投稿。
	if strings.TrimSpace(video.GeneratedDesc) == "通过自动化工具上传的视频" ||
		strings.TrimSpace(video.GeneratedDesc) == "" {
		return nil, fmt.Errorf("上传前校验失败: 简介未生成中文内容，禁止上传")
	}
	if !hasChineseRunes(video.GeneratedTitle) && !hasChineseRunes(video.Title) {
		return nil, fmt.Errorf("上传前校验失败: 标题缺少中文，禁止上传")
	}
	if !hasChineseRunes(video.GeneratedDesc) {
		return nil, fmt.Errorf("上传前校验失败: 简介缺少中文，禁止上传")
	}
	if !hasZhSubtitleBesideVideo(video.VideoPath) {
		return nil, fmt.Errorf("上传前校验失败: 未找到中文字幕，禁止上传原片")
	}
'''
        if old in s:
            s = s.replace(old, new, 1)
            # add helpers at end
            s += '''

func hasChineseRunes(s string) bool {
	for _, r := range s {
		if r >= 0x4e00 && r <= 0x9fff {
			return true
		}
	}
	return false
}

func hasZhSubtitleBesideVideo(videoPath string) bool {
	dir := filepath.Dir(videoPath)
	base := strings.TrimSuffix(filepath.Base(videoPath), filepath.Ext(videoPath))
	for _, p := range []string{
		filepath.Join(dir, "zh.srt"),
		filepath.Join(dir, base+".zh.srt"),
		filepath.Join(dir, base+".zh-CN.srt"),
	} {
		if st, err := os.Stat(p); err == nil && !st.IsDir() && st.Size() > 0 {
			return true
		}
	}
	matches, _ := filepath.Glob(filepath.Join(dir, "*.zh.srt"))
	return len(matches) > 0
}
'''
            # imports
            if "path/filepath" not in s:
                s = s.replace("import (\n", "import (\n\t\"os\"\n\t\"path/filepath\"\n", 1)
            if "strings" not in s.split("import (")[1].split(")")[0]:
                s = s.replace("import (\n", "import (\n\t\"strings\"\n", 1)
            print("helper gated")
        else:
            print("upload helper insert point missing")
    p.write_text(s)
