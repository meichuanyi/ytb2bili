from pathlib import Path

# handler test method
p = Path("internal/handler/system_settings_handler.go")
s = p.read_text()
if "NotifyTest" not in s:
    s = s.replace(
        '''type SystemSettingsHandler struct {
	settings  *service.SystemSettingsClient
	logger    *zap.Logger
	jwtSecret string
}''',
        '''type SystemSettingsHandler struct {
	settings  *service.SystemSettingsClient
	logger    *zap.Logger
	jwtSecret string
	notifier  *service.Notifier
}''',
    )
    s = s.replace(
        '''func NewSystemSettingsHandler(settings *service.SystemSettingsClient, logger *zap.Logger, cfg *config.AppConfig) *SystemSettingsHandler {
	jwtSecret := ""
	if cfg != nil {
		jwtSecret = strings.TrimSpace(cfg.Auth.JWTSecret)
	}

	return &SystemSettingsHandler{
		settings:  settings,
		logger:    logger,
		jwtSecret: jwtSecret,
	}
}''',
        '''func NewSystemSettingsHandler(settings *service.SystemSettingsClient, logger *zap.Logger, cfg *config.AppConfig, notifier *service.Notifier) *SystemSettingsHandler {
	jwtSecret := ""
	if cfg != nil {
		jwtSecret = strings.TrimSpace(cfg.Auth.JWTSecret)
	}

	return &SystemSettingsHandler{
		settings:  settings,
		logger:    logger,
		jwtSecret: jwtSecret,
		notifier:  notifier,
	}
}

// NotifyTest 发送一条测试通知，用于前端验证配置。
func (h *SystemSettingsHandler) NotifyTest(c *gin.Context) {
	if h.notifier == nil || !h.notifier.Enabled() {
		BadRequest(c, "通知未启用或未配置任何渠道")
		return
	}
	uid := c.GetString("uid")
	h.notifier.NotifyAsync(c.Request.Context(), service.NotifyPayload{
		Event:   service.NotifyEventVideoCompleted,
		Title:   "ytb2bili 测试通知",
		Message: "通知渠道配置有效。",
		UserID:  uid,
		Status:  "test",
	})
	Success(c, gin.H{"ok": true, "message": "测试通知已提交"})
}''',
    )
    s = s.replace(
        '''		group.GET("", h.GetSettings)
			group.PUT("", h.UpdateSettings)''',
        '''		group.GET("", h.GetSettings)
			group.PUT("", h.UpdateSettings)
			group.POST("/notify/test", h.NotifyTest)''',
    )
    p.write_text(s)
    print("handler test endpoint added")
else:
    print("handler already has NotifyTest")
