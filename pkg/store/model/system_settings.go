package model

import (
	"fmt"
	"strconv"
	"strings"
)

const (
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

	DefaultYouTubeFeedSyncIntervalMinutes = 60
	DefaultYouTubeFeedSyncLookbackDays    = 7
)

var allowedYouTubeFeedSyncIntervals = map[int]struct{}{
	15:   {},
	30:   {},
	60:   {},
	120:  {},
	180:  {},
	360:  {},
	720:  {},
	1440: {},
}

var allowedYouTubeFeedSyncLookbackDays = map[int]struct{}{
	1:  {},
	3:  {},
	7:  {},
	14: {},
	30: {},
	90: {},
}

type SystemSettings struct {
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
}

func (SystemSettings) TableName() string {
	return "tb_system_settings"
}

func DefaultSystemSettings() *SystemSettings {
	return &SystemSettings{
		SingletonKey:                   "default",
		YouTubeFeedSyncEnabled:         true,
		YouTubeFeedSyncIntervalMinutes: DefaultYouTubeFeedSyncIntervalMinutes,
		YouTubeFeedSyncLookbackDays:    DefaultYouTubeFeedSyncLookbackDays,
	}
}

func IsAllowedYouTubeFeedSyncIntervalMinutes(value int) bool {
	_, ok := allowedYouTubeFeedSyncIntervals[value]
	return ok
}

func NormalizeYouTubeFeedSyncIntervalMinutes(value int) int {
	if IsAllowedYouTubeFeedSyncIntervalMinutes(value) {
		return value
	}
	return DefaultYouTubeFeedSyncIntervalMinutes
}

func IsAllowedYouTubeFeedSyncLookbackDays(value int) bool {
	_, ok := allowedYouTubeFeedSyncLookbackDays[value]
	return ok
}

func NormalizeYouTubeFeedSyncLookbackDays(value int) int {
	if IsAllowedYouTubeFeedSyncLookbackDays(value) {
		return value
	}
	return DefaultYouTubeFeedSyncLookbackDays
}

func (settings *SystemSettings) ToSettingsMap() map[string]string {
	return map[string]string{
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
	}
}

func (settings *SystemSettings) ApplySettingsPatch(patch map[string]string) error {
	for key, rawValue := range patch {
		value := strings.TrimSpace(rawValue)
		switch key {
		case SystemSettingKeyYouTubeFeedSyncEnabled:
			enabled, err := parseBoolSettingValue(value)
			if err != nil {
				return err
			}
			settings.YouTubeFeedSyncEnabled = enabled
		case SystemSettingKeyYouTubeFeedSyncInterval:
			minutes, err := strconv.Atoi(value)
			if err != nil {
				return fmt.Errorf("invalid youtube feed sync interval: %s", value)
			}
			if !IsAllowedYouTubeFeedSyncIntervalMinutes(minutes) {
				return fmt.Errorf("unsupported youtube feed sync interval: %d", minutes)
			}
			settings.YouTubeFeedSyncIntervalMinutes = minutes
		case SystemSettingKeyYouTubeFeedSyncLookback:
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
		}
	}

	settings.YouTubeFeedSyncIntervalMinutes = NormalizeYouTubeFeedSyncIntervalMinutes(settings.YouTubeFeedSyncIntervalMinutes)
	settings.YouTubeFeedSyncLookbackDays = NormalizeYouTubeFeedSyncLookbackDays(settings.YouTubeFeedSyncLookbackDays)
	if strings.TrimSpace(settings.SingletonKey) == "" {
		settings.SingletonKey = "default"
	}
	return nil
}