package workflow

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
