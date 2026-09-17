package workflow

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"github.com/difyz9/ytb2bili/internal/config"
	"go.uber.org/fx"
	"go.uber.org/zap"
)

// ============================================================================
// 步骤: 中文配音合成
// 将 SynthesizeSubtitleAudioStep 产出的各字幕配音片段，按字幕时间轴叠加到
// 视频音轨上（原声压低作背景），替换原声轨，实现「中文配音替换英文原声」。
// ============================================================================

const StepNameDubAudio = "DubAudio"

type DubAudioStep struct {
	BaseStep
	ffmpegPath string
	logger     *zap.Logger
}

type DubAudioStepParams struct {
	fx.In
	Cfg    config.WorkflowConfig
	Logger *zap.Logger
}

func NewDubAudioStep(params DubAudioStepParams) *DubAudioStep {
	ffmpegPath := strings.TrimSpace(params.Cfg.FFmpegPath)
	if ffmpegPath == "" {
		ffmpegPath = "ffmpeg"
	}
	return &DubAudioStep{
		BaseStep:   NewBaseStepWithOrder(StepNameDubAudio, false, 8),
		ffmpegPath: ffmpegPath,
		logger:     params.Logger,
	}
}

func (s *DubAudioStep) Name() string { return StepNameDubAudio }

type dubClip struct {
	path    string
	startMs int
}

// Execute 执行配音合成。
func (s *DubAudioStep) Execute(ctx context.Context, input interface{}) (interface{}, error) {
	vctx, ok := input.(*VideoContext)
	if !ok {
		return nil, fmt.Errorf("invalid input type: expected *VideoContext, got %T", input)
	}

	videoPath := strings.TrimSpace(vctx.VideoPath)
	if videoPath == "" {
		s.logger.Warn("没有视频文件，跳过配音合成")
		return vctx, nil
	}
	if _, err := os.Stat(videoPath); err != nil {
		s.logger.Warn("视频文件不存在，跳过配音合成", zap.String("path", videoPath))
		return vctx, nil
	}

	// 收集有效配音片段；按中文实际时长顺序排轨，避免下一句盖住未说完的话。
	type placedClip struct {
		dubClip
		idx    int
		endMs  int
		origMs int
	}
	clips := make([]dubClip, 0, len(vctx.SubtitleAudios))
	placed := make([]placedClip, 0, len(vctx.SubtitleAudios))
	prevEndMs := 0
	const gapMs = 80
	for i := range vctx.SubtitleAudios {
		sub := &vctx.SubtitleAudios[i]
		p := strings.TrimSpace(sub.AudioPath)
		if p == "" || strings.TrimSpace(sub.TranslatedText) == "" {
			continue
		}
		if _, err := os.Stat(p); err != nil {
			continue
		}
		origStart := sub.StartTime
		if origStart < 0 {
			origStart = 0
		}
		origMs := int(origStart * 1000)
		durMs := audioDurationMs(ctx, s.ffmpegPath, p)
		if durMs <= 0 {
			// 退回原槽位长度估计
			origEnd := sub.EndTime
			if origEnd <= origStart {
				origEnd = origStart + 3
			}
			durMs = int((origEnd - origStart) * 1000)
		}
		startMs := origMs
		if startMs < prevEndMs+gapMs {
			startMs = prevEndMs + gapMs
		}
		endMs := startMs + durMs
		clips = append(clips, dubClip{path: p, startMs: startMs})
		placed = append(placed, placedClip{dubClip: clips[len(clips)-1], idx: i, endMs: endMs, origMs: origMs})
		prevEndMs = endMs
		// 回写时间轴，便于后续字幕与画面大致对齐
		sub.StartTime = float64(startMs) / 1000.0
		sub.EndTime = float64(endMs) / 1000.0
	}
	if len(placed) > 0 {
		s.logger.Info("配音轨道已按实际时长重排",
			zap.Int("clips", len(clips)),
			zap.Int("last_end_ms", prevEndMs),
			zap.Int("first_orig_ms", placed[0].origMs))
	}
	if len(clips) == 0 {
		s.logger.Warn("没有可用的配音片段，视频保留原声",
			zap.String("videoID", vctx.VideoID))
		return vctx, nil
	}

	if _, err := exec.LookPath(s.ffmpegPath); err != nil {
		s.logger.Warn("ffmpeg 不可用，跳过配音合成", zap.String("path", s.ffmpegPath))
		return vctx, nil
	}

	// 构造 ffmpeg 命令：
	//   输入 0: 原视频；输入 1..N: 各配音片段
	//   原声压低至 15% 作背景；配音片段按 adelay 平移到字幕起始时间；
	//   统一重采样后 amix 汇总，替换视频音轨（视频流直接 copy）。
	args := []string{"-y", "-i", videoPath}
	for _, c := range clips {
		args = append(args, "-i", c.path)
	}

	filterParts := make([]string, 0, len(clips)+2)
	filterParts = append(filterParts, "[0:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.15[bg]")
	for i, c := range clips {
		filterParts = append(filterParts,
			fmt.Sprintf("[%d:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay=%d:all=1[a%d]", i+1, c.startMs, i+1))
	}
	mixInputs := make([]string, 0, len(clips)+1)
	mixInputs = append(mixInputs, "[bg]")
	for i := range clips {
		mixInputs = append(mixInputs, fmt.Sprintf("[a%d]", i+1))
	}
	filterParts = append(filterParts,
		fmt.Sprintf("%samix=inputs=%d:normalize=0:duration=longest[dub]", strings.Join(mixInputs, ""), len(clips)+1))

	outPath := filepath.Join(filepath.Dir(videoPath), "dubbed_"+filepath.Base(videoPath))
	args = append(args,
		"-filter_complex", strings.Join(filterParts, ";"),
		"-map", "0:v", "-map", "[dub]",
		"-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
		outPath,
	)

	cmd := exec.CommandContext(ctx, s.ffmpegPath, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		_ = os.Remove(outPath)
		tail := string(out)
		if len(tail) > 400 {
			tail = tail[len(tail)-400:]
		}
		return vctx, fmt.Errorf("配音合成失败: %v: %s", err, tail)
	}

	if err := os.Rename(outPath, videoPath); err != nil {
		_ = os.Remove(outPath)
		return vctx, fmt.Errorf("替换视频音轨失败: %w", err)
	}

	s.logger.Info("中文配音合成完成，已替换视频原声",
		zap.String("videoID", vctx.VideoID),
		zap.Int("clip_count", len(clips)),
		zap.String("video_path", videoPath))
	return vctx, nil
}

func audioDurationMs(ctx context.Context, ffmpegPath, path string) int {
	// ffprobe 若不存在则用 ffmpeg 解析 duration
	probe := strings.Replace(ffmpegPath, "ffmpeg", "ffprobe", 1)
	if _, err := exec.LookPath(probe); err != nil {
		probe = "ffprobe"
	}
	if _, err := exec.LookPath(probe); err == nil {
		cmd := exec.CommandContext(ctx, probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path)
		out, err := cmd.Output()
		if err == nil {
			var sec float64
			if _, scanErr := fmt.Sscanf(strings.TrimSpace(string(out)), "%f", &sec); scanErr == nil && sec > 0 {
				return int(sec * 1000)
			}
		}
	}
	cmd := exec.CommandContext(ctx, ffmpegPath, "-i", path)
	b, _ := cmd.CombinedOutput()
	// parse Duration: 00:00:03.45
	re := regexp.MustCompile(`Duration: (\d+):(\d+):(\d+\.\d+)`)
	m := re.FindStringSubmatch(string(b))
	if m == nil {
		return 0
	}
	h, _ := strconv.ParseFloat(m[1], 64)
	mm, _ := strconv.ParseFloat(m[2], 64)
	ss, _ := strconv.ParseFloat(m[3], 64)
	return int((h*3600 + mm*60 + ss) * 1000)
}
