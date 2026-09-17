from pathlib import Path

# 1) NotifyConfig in app_config.go
p = Path("internal/config/app_config.go")
s = p.read_text()
if "NotifyConfig" not in s:
    s = s.replace(
        "\tWorkflow     WorkflowConfig     `toml:\"workflow\"`\n\tAgentOpenAPI AgentOpenAPIConfig `toml:\"agent_open_api\"`\n}",
        "\tWorkflow     WorkflowConfig     `toml:\"workflow\"`\n\tAgentOpenAPI AgentOpenAPIConfig `toml:\"agent_open_api\"`\n\tNotify       NotifyConfig       `toml:\"notify\"`\n}\n\n// NotifyConfig 出站通知（webhook / ntfy / Bark / Telegram / 钉钉 / 飞书 / 企微）。\ntype NotifyConfig struct {\n\tEnabled bool `toml:\"enabled\"`\n\t// WebhookURL 通用 JSON POST，body 见 NotifyPayload。\n\tWebhookURL string `toml:\"webhook_url\"`\n\t// NtfyURL 形如 http://ntfy.sh/topic 或自建 http://host/topic\n\tNtfyURL string `toml:\"ntfy_url\"`\n\t// BarkURL 形如 https://api.day.app/<key>/<title>/<body> 或 https://api.day.app/<key>\n\tBarkURL string `toml:\"bark_url\"`\n\t// TelegramBotToken + TelegramChatID\n\tTelegramBotToken string `toml:\"telegram_bot_token\"`\n\tTelegramChatID   string `toml:\"telegram_chat_id\"`\n\t// 钉钉/飞书/企微自定义机器人 webhook\n\tDingTalkWebhook string `toml:\"dingtalk_webhook\"`\n\tFeishuBotWebhook string `toml:\"feishu_bot_webhook\"`\n\tWeComWebhook     string `toml:\"wecom_webhook\"`\n\t// Events 过滤，空=全部；可选 video.completed / video.failed / bilibili.uploaded\n\tEvents []string `toml:\"events,omitempty\"`\n\t// TimeoutSec 默认 10\n\tTimeoutSec int `toml:\"timeout_sec\"`\n}",
    )
    p.write_text(s)
    print("app_config patched")
else:
    print("app_config already has NotifyConfig")

# 2) notifier service
notifier = r'''package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/difyz9/ytb2bili/internal/config"
	"go.uber.org/zap"
)

// NotifyEvent is a stable event name for filtering.
const (
	NotifyEventVideoCompleted   = "video.completed"
	NotifyEventVideoFailed      = "video.failed"
	NotifyEventBilibiliUploaded = "bilibili.uploaded"
)

// NotifyPayload is the JSON body posted to generic webhook_url.
type NotifyPayload struct {
	Event     string            `json:"event"`
	Title     string            `json:"title"`
	Message   string            `json:"message"`
	VideoID   string            `json:"video_id,omitempty"`
	UserID    string            `json:"user_id,omitempty"`
	Status    string            `json:"status,omitempty"`
	Extra     map[string]string `json:"extra,omitempty"`
	Timestamp time.Time         `json:"timestamp"`
}

// Notifier sends outbound notifications (fire-and-forget).
type Notifier struct {
	cfg    config.NotifyConfig
	logger *zap.Logger
	client *http.Client
}

func NewNotifier(cfg config.NotifyConfig, logger *zap.Logger) *Notifier {
	timeout := time.Duration(cfg.TimeoutSec) * time.Second
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &Notifier{
		cfg:    cfg,
		logger: logger,
		client: &http.Client{Timeout: timeout},
	}
}

func (n *Notifier) Enabled() bool {
	if n == nil || !n.cfg.Enabled {
		return false
	}
	return n.cfg.WebhookURL != "" || n.cfg.NtfyURL != "" || n.cfg.BarkURL != "" ||
		n.cfg.TelegramBotToken != "" || n.cfg.DingTalkWebhook != "" ||
		n.cfg.FeishuBotWebhook != "" || n.cfg.WeComWebhook != ""
}

func (n *Notifier) eventAllowed(event string) bool {
	if len(n.cfg.Events) == 0 {
		return true
	}
	for _, e := range n.cfg.Events {
		if strings.EqualFold(strings.TrimSpace(e), event) {
			return true
		}
	}
	return false
}

// NotifyAsync fires all configured channels without blocking the caller.
func (n *Notifier) NotifyAsync(ctx context.Context, p NotifyPayload) {
	if !n.Enabled() || !n.eventAllowed(p.Event) {
		return
	}
	if p.Timestamp.IsZero() {
		p.Timestamp = time.Now()
	}
	if p.Title == "" {
		p.Title = p.Event
	}
	payload := p
	go func() {
		bg, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		_ = bg
		n.sendAll(payload)
	}()
}

func (n *Notifier) sendAll(p NotifyPayload) {
	if n.cfg.WebhookURL != "" {
		n.postJSON(n.cfg.WebhookURL, p, nil)
	}
	if n.cfg.NtfyURL != "" {
		n.sendNtfy(p)
	}
	if n.cfg.BarkURL != "" {
		n.sendBark(p)
	}
	if n.cfg.TelegramBotToken != "" && n.cfg.TelegramChatID != "" {
		n.sendTelegram(p)
	}
	text := fmt.Sprintf("【%s】\n%s\nvideo=%s status=%s", p.Title, p.Message, p.VideoID, p.Status)
	if n.cfg.DingTalkWebhook != "" {
		n.postJSON(n.cfg.DingTalkWebhook, map[string]any{
			"msgtype": "text",
			"text":    map[string]string{"content": text},
		}, nil)
	}
	if n.cfg.FeishuBotWebhook != "" {
		n.postJSON(n.cfg.FeishuBotWebhook, map[string]any{
			"msg_type": "text",
			"content":  map[string]string{"text": text},
		}, nil)
	}
	if n.cfg.WeComWebhook != "" {
		n.postJSON(n.cfg.WeComWebhook, map[string]any{
			"msgtype": "text",
			"text":    map[string]string{"content": text},
		}, nil)
	}
}

func (n *Notifier) sendNtfy(p NotifyPayload) {
	req, err := http.NewRequest(http.MethodPost, n.cfg.NtfyURL, strings.NewReader(p.Message))
	if err != nil {
		n.logger.Warn("notify ntfy build failed", zap.Error(err))
		return
	}
	req.Header.Set("Title", p.Title)
	req.Header.Set("Priority", "default")
	req.Header.Set("Tags", "bell")
	if resp, err := n.client.Do(req); err != nil {
		n.logger.Warn("notify ntfy failed", zap.Error(err))
	} else {
		_ = resp.Body.Close()
	}
}

func (n *Notifier) sendBark(p NotifyPayload) {
	url := strings.TrimRight(n.cfg.BarkURL, "/")
	body, _ := json.Marshal(map[string]string{"title": p.Title, "body": p.Message, "group": "ytb2bili"})
	if err := n.postJSON(url, json.RawMessage(body), map[string]string{"Content-Type": "application/json"}); err != nil {
		// fallback GET style
		getURL := fmt.Sprintf("%s/%s/%s", url, urlEncode(p.Title), urlEncode(p.Message))
		if resp, err2 := n.client.Get(getURL); err2 == nil {
			_ = resp.Body.Close()
		}
	}
}

func (n *Notifier) sendTelegram(p NotifyPayload) {
	api := fmt.Sprintf("https://api.telegram.org/bot%s/sendMessage", n.cfg.TelegramBotToken)
	body := map[string]any{
		"chat_id": n.cfg.TelegramChatID,
		"text":    fmt.Sprintf("%s\n%s", p.Title, p.Message),
	}
	n.postJSON(api, body, nil)
}

func (n *Notifier) postJSON(url string, body any, headers map[string]string) error {
	var reader *bytes.Reader
	switch b := body.(type) {
	case json.RawMessage:
		reader = bytes.NewReader(b)
	default:
		data, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(data)
	}
	req, err := http.NewRequest(http.MethodPost, url, reader)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := n.client.Do(req)
	if err != nil {
		n.logger.Warn("notify post failed", zap.String("url", url), zap.Error(err))
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		n.logger.Warn("notify post non-2xx", zap.String("url", url), zap.Int("status", resp.StatusCode))
	}
	return nil
}

func urlEncode(s string) string {
	return strings.ReplaceAll(strings.ReplaceAll(s, " ", "%20"), "/", "%2F")
}
'''
Path("internal/service/notifier.go").write_text(notifier)
print("notifier.go written")

# 3) provide in service module
mp = Path("internal/service/module.go")
ms = mp.read_text()
if "NewNotifier" not in ms:
    if "fx.Provide(" in ms:
        ms = ms.replace("fx.Provide(", "fx.Provide(\n\t\tNewNotifier,", 1)
    else:
        ms += "\n// see module.go for NewNotifier provide\n"
    mp.write_text(ms)
    print("module patched, content head:")
    print(ms[:800])
else:
    print("module already provides Notifier")
