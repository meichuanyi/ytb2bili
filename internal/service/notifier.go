package service

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
	NotifyEventVideoWarning    = "video.warning"
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
	cfg            config.NotifyConfig
	logger         *zap.Logger
	client         *http.Client
	systemSettings *SystemSettingsClient
}

func NewNotifier(appCfg *config.AppConfig, logger *zap.Logger, systemSettings *SystemSettingsClient) *Notifier {
	var cfg config.NotifyConfig
	if appCfg != nil {
		cfg = appCfg.Notify
	}
	timeout := time.Duration(cfg.TimeoutSec) * time.Second
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &Notifier{
		cfg:            cfg,
		logger:         logger,
		client:         &http.Client{Timeout: timeout},
		systemSettings: systemSettings,
	}
}

// effective merges config.toml with DB system settings (DB wins when set).
func (n *Notifier) effective() config.NotifyConfig {
	cfg := n.cfg
	if n.systemSettings == nil || !n.systemSettings.IsEnabled() {
		return cfg
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	st, err := n.systemSettings.GetSettingsRecord(ctx)
	if err != nil || st == nil {
		return cfg
	}
	// If DB has any notify field used, prefer full DB override for enabled+urls.
	// Enable: if DB row has been touched (enabled true) or any URL set, use DB enabled.
	dbHas := st.NotifyEnabled || st.NotifyWebhookURL != "" || st.NotifyMagicPushURL != "" ||
		st.NotifyNtfyURL != "" || st.NotifyBarkURL != "" || st.NotifyTelegramBotToken != "" ||
		st.NotifyDingTalkWebhook != "" || st.NotifyFeishuBotWebhook != "" || st.NotifyWeComWebhook != ""
	if dbHas {
		cfg.Enabled = st.NotifyEnabled
		cfg.WebhookURL = strings.TrimSpace(st.NotifyWebhookURL)
		cfg.MagicPushURL = strings.TrimSpace(st.NotifyMagicPushURL)
		cfg.NtfyURL = strings.TrimSpace(st.NotifyNtfyURL)
		cfg.BarkURL = strings.TrimSpace(st.NotifyBarkURL)
		cfg.TelegramBotToken = strings.TrimSpace(st.NotifyTelegramBotToken)
		cfg.TelegramChatID = strings.TrimSpace(st.NotifyTelegramChatID)
		cfg.DingTalkWebhook = strings.TrimSpace(st.NotifyDingTalkWebhook)
		cfg.FeishuBotWebhook = strings.TrimSpace(st.NotifyFeishuBotWebhook)
		cfg.WeComWebhook = strings.TrimSpace(st.NotifyWeComWebhook)
		if strings.TrimSpace(st.NotifyEvents) != "" {
			parts := strings.Split(st.NotifyEvents, ",")
			ev := make([]string, 0, len(parts))
			for _, p := range parts {
				p = strings.TrimSpace(p)
				if p != "" {
					ev = append(ev, p)
				}
			}
			cfg.Events = ev
		}
	}
	return cfg
}

func (n *Notifier) Enabled() bool {
	if n == nil {
		return false
	}
	cfg := n.effective()
	if !cfg.Enabled {
		return false
	}
	return cfg.WebhookURL != "" || cfg.NtfyURL != "" || cfg.BarkURL != "" || cfg.MagicPushURL != "" ||
		cfg.TelegramBotToken != "" || cfg.DingTalkWebhook != "" ||
		cfg.FeishuBotWebhook != "" || cfg.WeComWebhook != ""
}

func (n *Notifier) eventAllowed(event string) bool {
	cfg := n.effective()
	if len(cfg.Events) == 0 {
		return true
	}
	for _, e := range cfg.Events {
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
	cfg := n.effective()
	if cfg.WebhookURL != "" {
		n.postJSON(cfg.WebhookURL, p, nil)
	}
	if cfg.MagicPushURL != "" {
		n.sendMagicPushURL(cfg.MagicPushURL, p)
	}
	if cfg.NtfyURL != "" {
		n.sendNtfyURL(cfg.NtfyURL, p)
	}
	if cfg.BarkURL != "" {
		n.sendBarkURL(cfg.BarkURL, p)
	}
	if cfg.TelegramBotToken != "" && cfg.TelegramChatID != "" {
		n.sendTelegramCfg(cfg.TelegramBotToken, cfg.TelegramChatID, p)
	}
	text := fmt.Sprintf("【%s】\n%s\nvideo=%s status=%s", p.Title, p.Message, p.VideoID, p.Status)
	if cfg.DingTalkWebhook != "" {
		n.postJSON(cfg.DingTalkWebhook, map[string]any{
			"msgtype": "text",
			"text":    map[string]string{"content": text},
		}, nil)
	}
	if cfg.FeishuBotWebhook != "" {
		n.postJSON(cfg.FeishuBotWebhook, map[string]any{
			"msg_type": "text",
			"content":  map[string]string{"text": text},
		}, nil)
	}
	if cfg.WeComWebhook != "" {
		n.postJSON(cfg.WeComWebhook, map[string]any{
			"msgtype": "text",
			"text":    map[string]string{"content": text},
		}, nil)
	}
}

func (n *Notifier) sendMagicPushURL(url string, p NotifyPayload) {
	// MagicPush: POST /api/push/{token} body {title, content, type}
	type mpBody struct {
		Title   string `json:"title"`
		Content string `json:"content"`
		Type    string `json:"type"`
		URL     string `json:"url,omitempty"`
	}
	msg := p.Message
	if msg == "" {
		msg = p.Title
	}
	n.postJSON(url, mpBody{
		Title:   p.Title,
		Content: msg,
		Type:    "text",
	}, nil)
}

func (n *Notifier) sendNtfyURL(ntfyURL string, p NotifyPayload) {
	req, err := http.NewRequest(http.MethodPost, ntfyURL, strings.NewReader(p.Message))
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

func (n *Notifier) sendBarkURL(barkURL string, p NotifyPayload) {
	url := strings.TrimRight(barkURL, "/")
	body, _ := json.Marshal(map[string]string{"title": p.Title, "body": p.Message, "group": "ytb2bili"})
	if err := n.postJSON(url, json.RawMessage(body), map[string]string{"Content-Type": "application/json"}); err != nil {
		// fallback GET style
		getURL := fmt.Sprintf("%s/%s/%s", url, urlEncode(p.Title), urlEncode(p.Message))
		if resp, err2 := n.client.Get(getURL); err2 == nil {
			_ = resp.Body.Close()
		}
	}
}

func (n *Notifier) sendTelegramCfg(botToken, chatID string, p NotifyPayload) {
	api := fmt.Sprintf("https://api.telegram.org/bot%s/sendMessage", botToken)
	body := map[string]any{
		"chat_id": chatID,
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
