from pathlib import Path

# ── 1) model ──
p = Path("pkg/store/model/system_settings.go")
s = p.read_text()
if "NotifyEnabled" not in s:
    s = s.replace(
        'const (\n\tSystemSettingKeyYouTubeFeedSyncEnabled  = "youtube_feed_sync_enabled"\n\tSystemSettingKeyYouTubeFeedSyncInterval = "youtube_feed_sync_interval_minutes"\n\tSystemSettingKeyYouTubeFeedSyncLookback = "youtube_feed_sync_lookback_days"\n',
        '''const (
	SystemSettingKeyYouTubeFeedSyncEnabled  = "youtube_feed_sync_enabled"
	SystemSettingKeyYouTubeFeedSyncInterval = "youtube_feed_sync_interval_minutes"
	SystemSettingKeyYouTubeFeedSyncLookback = "youtube_feed_sync_lookback_days"
	SystemSettingKeyNotifyEnabled           = "notify_enabled"
	SystemSettingKeyNotifyWebhookURL        = "notify_webhook_url"
	SystemSettingKeyNotifyMagicPushURL      = "notify_magicpush_url"
	SystemSettingKeyNotifyNtfyURL           = "notify_ntfy_url"
	SystemSettingKeyNotifyBarkURL           = "notify_bark_url"
	SystemSettingKeyNotifyTelegramBotToken  = "notify_telegram_bot_token"
	SystemSettingKeyNotifyTelegramChatID    = "notify_telegram_chat_id"
	SystemSettingKeyNotifyDingTalkWebhook   = "notify_dingtalk_webhook"
	SystemSettingKeyNotifyFeishuBotWebhook  = "notify_feishu_bot_webhook"
	SystemSettingKeyNotifyWeComWebhook      = "notify_wecom_webhook"
	SystemSettingKeyNotifyEvents            = "notify_events"
''',
    )
    s = s.replace(
        '''type SystemSettings struct {
	BaseModel
	SingletonKey                   string `gorm:"uniqueIndex;size:64;not null" json:"singleton_key"`
	YouTubeFeedSyncEnabled         bool   `gorm:"default:true" json:"youtube_feed_sync_enabled"`
	YouTubeFeedSyncIntervalMinutes int    `gorm:"default:60" json:"youtube_feed_sync_interval_minutes"`
	YouTubeFeedSyncLookbackDays    int    `gorm:"default:7" json:"youtube_feed_sync_lookback_days"`
}''',
        '''type SystemSettings struct {
	BaseModel
	SingletonKey                   string `gorm:"uniqueIndex;size:64;not null" json:"singleton_key"`
	YouTubeFeedSyncEnabled         bool   `gorm:"default:true" json:"youtube_feed_sync_enabled"`
	YouTubeFeedSyncIntervalMinutes int    `gorm:"default:60" json:"youtube_feed_sync_interval_minutes"`
	YouTubeFeedSyncLookbackDays    int    `gorm:"default:7" json:"youtube_feed_sync_lookback_days"`
	NotifyEnabled                  bool   `gorm:"default:false" json:"notify_enabled"`
	NotifyWebhookURL               string `gorm:"size:500" json:"notify_webhook_url"`
	NotifyMagicPushURL             string `gorm:"size:500" json:"notify_magicpush_url"`
	NotifyNtfyURL                  string `gorm:"size:500" json:"notify_ntfy_url"`
	NotifyBarkURL                  string `gorm:"size:500" json:"notify_bark_url"`
	NotifyTelegramBotToken         string `gorm:"size:255" json:"notify_telegram_bot_token"`
	NotifyTelegramChatID           string `gorm:"size:64" json:"notify_telegram_chat_id"`
	NotifyDingTalkWebhook          string `gorm:"size:500" json:"notify_dingtalk_webhook"`
	NotifyFeishuBotWebhook         string `gorm:"size:500" json:"notify_feishu_bot_webhook"`
	NotifyWeComWebhook             string `gorm:"size:500" json:"notify_wecom_webhook"`
	NotifyEvents                   string `gorm:"size:255" json:"notify_events"`
}''',
    )
    s = s.replace(
        '''	return map[string]string{
		SystemSettingKeyYouTubeFeedSyncEnabled:  boolToSettingValue(settings.YouTubeFeedSyncEnabled),
		SystemSettingKeyYouTubeFeedSyncInterval: strconv.Itoa(NormalizeYouTubeFeedSyncIntervalMinutes(settings.YouTubeFeedSyncIntervalMinutes)),
		SystemSettingKeyYouTubeFeedSyncLookback: strconv.Itoa(NormalizeYouTubeFeedSyncLookbackDays(settings.YouTubeFeedSyncLookbackDays)),
	}''',
        '''	return map[string]string{
		SystemSettingKeyYouTubeFeedSyncEnabled:  boolToSettingValue(settings.YouTubeFeedSyncEnabled),
		SystemSettingKeyYouTubeFeedSyncInterval: strconv.Itoa(NormalizeYouTubeFeedSyncIntervalMinutes(settings.YouTubeFeedSyncIntervalMinutes)),
		SystemSettingKeyYouTubeFeedSyncLookback: strconv.Itoa(NormalizeYouTubeFeedSyncLookbackDays(settings.YouTubeFeedSyncLookbackDays)),
		SystemSettingKeyNotifyEnabled:           boolToSettingValue(settings.NotifyEnabled),
		SystemSettingKeyNotifyWebhookURL:        settings.NotifyWebhookURL,
		SystemSettingKeyNotifyMagicPushURL:      settings.NotifyMagicPushURL,
		SystemSettingKeyNotifyNtfyURL:           settings.NotifyNtfyURL,
		SystemSettingKeyNotifyBarkURL:           settings.NotifyBarkURL,
		SystemSettingKeyNotifyTelegramBotToken:  settings.NotifyTelegramBotToken,
		SystemSettingKeyNotifyTelegramChatID:    settings.NotifyTelegramChatID,
		SystemSettingKeyNotifyDingTalkWebhook:   settings.NotifyDingTalkWebhook,
		SystemSettingKeyNotifyFeishuBotWebhook:  settings.NotifyFeishuBotWebhook,
		SystemSettingKeyNotifyWeComWebhook:      settings.NotifyWeComWebhook,
		SystemSettingKeyNotifyEvents:            settings.NotifyEvents,
	}''',
    )
    # ApplySettingsPatch
    s = s.replace(
        '''		case SystemSettingKeyYouTubeFeedSyncLookback:
			days, err := strconv.Atoi(value)
			if err != nil {
				return fmt.Errorf("invalid youtube feed sync lookback days: %s", value)
			}
			if !IsAllowedYouTubeFeedSyncLookbackDays(days) {
				return fmt.Errorf("unsupported youtube feed sync lookback days: %d", days)
			}
			settings.YouTubeFeedSyncLookbackDays = days
		default:
			return fmt.Errorf("unsupported system setting key: %s", key)
		}''',
        '''		case SystemSettingKeyYouTubeFeedSyncLookback:
			days, err := strconv.Atoi(value)
			if err != nil {
				return fmt.Errorf("invalid youtube feed sync lookback days: %s", value)
			}
			if !IsAllowedYouTubeFeedSyncLookbackDays(days) {
				return fmt.Errorf("unsupported youtube feed sync lookback days: %d", days)
			}
			settings.YouTubeFeedSyncLookbackDays = days
		case SystemSettingKeyNotifyEnabled:
			enabled, err := parseBoolSettingValue(value)
			if err != nil {
				return err
			}
			settings.NotifyEnabled = enabled
		case SystemSettingKeyNotifyWebhookURL:
			settings.NotifyWebhookURL = value
		case SystemSettingKeyNotifyMagicPushURL:
			settings.NotifyMagicPushURL = value
		case SystemSettingKeyNotifyNtfyURL:
			settings.NotifyNtfyURL = value
		case SystemSettingKeyNotifyBarkURL:
			settings.NotifyBarkURL = value
		case SystemSettingKeyNotifyTelegramBotToken:
			settings.NotifyTelegramBotToken = value
		case SystemSettingKeyNotifyTelegramChatID:
			settings.NotifyTelegramChatID = value
		case SystemSettingKeyNotifyDingTalkWebhook:
			settings.NotifyDingTalkWebhook = value
		case SystemSettingKeyNotifyFeishuBotWebhook:
			settings.NotifyFeishuBotWebhook = value
		case SystemSettingKeyNotifyWeComWebhook:
			settings.NotifyWeComWebhook = value
		case SystemSettingKeyNotifyEvents:
			settings.NotifyEvents = value
		default:
			return fmt.Errorf("unsupported system setting key: %s", key)
		}''',
    )
    p.write_text(s)
    print("model patched")
else:
    print("model already has notify")

# ── 2) Notifier reads system settings ──
p = Path("internal/service/notifier.go")
s = p.read_text()
if "systemSettings" not in s:
    s = s.replace(
        '''type Notifier struct {
	cfg    config.NotifyConfig
	logger *zap.Logger
	client *http.Client
}''',
        '''type Notifier struct {
	cfg            config.NotifyConfig
	logger         *zap.Logger
	client         *http.Client
	systemSettings *SystemSettingsClient
}''',
    )
    s = s.replace(
        '''func NewNotifier(appCfg *config.AppConfig, logger *zap.Logger) *Notifier {
	var cfg config.NotifyConfig
	if appCfg != nil {
		cfg = appCfg.Notify
	}
	timeout := time.Duration(cfg.TimeoutSec) * time.Second
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &Notifier{
		cfg:    cfg,
		logger: logger,
		client: &http.Client{Timeout: timeout},
	}
}''',
        '''func NewNotifier(appCfg *config.AppConfig, logger *zap.Logger, systemSettings *SystemSettingsClient) *Notifier {
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
}''',
    )
    # use effective in Enabled and sendAll
    s = s.replace(
        '''func (n *Notifier) Enabled() bool {
	if n == nil || !n.cfg.Enabled {
		return false
	}
	return n.cfg.WebhookURL != "" || n.cfg.NtfyURL != "" || n.cfg.BarkURL != "" || n.cfg.MagicPushURL != "" ||
		n.cfg.TelegramBotToken != "" || n.cfg.DingTalkWebhook != "" ||
		n.cfg.FeishuBotWebhook != "" || n.cfg.WeComWebhook != ""
}''',
        '''func (n *Notifier) Enabled() bool {
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
}''',
    )
    s = s.replace(
        '''func (n *Notifier) eventAllowed(event string) bool {
	if len(n.cfg.Events) == 0 {
		return true
	}
	for _, e := range n.cfg.Events {
		if strings.EqualFold(strings.TrimSpace(e), event) {
			return true
		}
	}
	return false
}''',
        '''func (n *Notifier) eventAllowed(event string) bool {
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
}''',
    )
    s = s.replace(
        '''func (n *Notifier) sendAll(p NotifyPayload) {
	if n.cfg.WebhookURL != "" {
		n.postJSON(n.cfg.WebhookURL, p, nil)
	}
	if n.cfg.MagicPushURL != "" {
		n.sendMagicPush(p)
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
	text := fmt.Sprintf("【%s】\\n%s\\nvideo=%s status=%s", p.Title, p.Message, p.VideoID, p.Status)
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
}''',
        '''func (n *Notifier) sendAll(p NotifyPayload) {
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
	text := fmt.Sprintf("【%s】\\n%s\\nvideo=%s status=%s", p.Title, p.Message, p.VideoID, p.Status)
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
}''',
    )
    # rename send methods to accept URL params
    s = s.replace("func (n *Notifier) sendMagicPush(p NotifyPayload) {", "func (n *Notifier) sendMagicPushURL(url string, p NotifyPayload) {")
    s = s.replace("n.postJSON(n.cfg.MagicPushURL, mpBody{", "n.postJSON(url, mpBody{")
    s = s.replace("func (n *Notifier) sendNtfy(p NotifyPayload) {", "func (n *Notifier) sendNtfyURL(ntfyURL string, p NotifyPayload) {")
    s = s.replace("req, err := http.NewRequest(http.MethodPost, n.cfg.NtfyURL, strings.NewReader(p.Message))", "req, err := http.NewRequest(http.MethodPost, ntfyURL, strings.NewReader(p.Message))")
    s = s.replace("func (n *Notifier) sendBark(p NotifyPayload) {", "func (n *Notifier) sendBarkURL(barkURL string, p NotifyPayload) {")
    s = s.replace("url := strings.TrimRight(n.cfg.BarkURL, \"/\")", "url := strings.TrimRight(barkURL, \"/\")")
    s = s.replace("func (n *Notifier) sendTelegram(p NotifyPayload) {", "func (n *Notifier) sendTelegramCfg(botToken, chatID string, p NotifyPayload) {")
    s = s.replace('api := fmt.Sprintf("https://api.telegram.org/bot%s/sendMessage", n.cfg.TelegramBotToken)', 'api := fmt.Sprintf("https://api.telegram.org/bot%s/sendMessage", botToken)')
    s = s.replace('"chat_id": n.cfg.TelegramChatID,', '"chat_id": chatID,')
    p.write_text(s)
    print("notifier patched for system settings")
else:
    print("notifier already uses system settings")
