package handler

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/difyz9/ytb2bili/internal/config"
	"github.com/difyz9/ytb2bili/internal/middleware"
	"github.com/difyz9/ytb2bili/internal/service"
	"go.uber.org/zap"
)

type SystemSettingsHandler struct {
	settings  *service.SystemSettingsClient
	logger    *zap.Logger
	jwtSecret string
	notifier  *service.Notifier
}

const systemSettingsDBTimeout = 5 * time.Second

func NewSystemSettingsHandler(settings *service.SystemSettingsClient, logger *zap.Logger, cfg *config.AppConfig, notifier *service.Notifier) *SystemSettingsHandler {
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
}

func (h *SystemSettingsHandler) GetSettings(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), systemSettingsDBTimeout)
	defer cancel()

	settings, err := h.settings.GetSettings(ctx)
	if err != nil {
		h.logger.Error("读取系统设置失败", zap.Error(err))
		InternalServerError(c, "读取系统设置失败")
		return
	}

	Success(c, gin.H{"settings": settings})
}

func (h *SystemSettingsHandler) UpdateSettings(c *gin.Context) {
	var patch map[string]string
	if err := c.ShouldBindJSON(&patch); err != nil {
		BadRequest(c, "请求体必须为 JSON 对象")
		return
	}
	if len(patch) == 0 {
		BadRequest(c, "无有效的设置项可更新")
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), systemSettingsDBTimeout)
	defer cancel()

	updated, err := h.settings.UpdateSettings(ctx, patch)
	if err != nil {
		h.logger.Warn("更新系统设置失败", zap.Error(err))
		BadRequest(c, fmt.Sprintf("更新系统设置失败: %v", err))
		return
	}

	Success(c, gin.H{"settings": updated.ToSettingsMap()})
}

func (h *SystemSettingsHandler) RegisterRoutes(r *gin.Engine) {
	anyAuth := middleware.AnyAuthMiddleware(h.jwtSecret)
	for _, basePath := range []string{"/api/v1/system/settings", "/api/system/settings", "/system/settings"} {
		group := r.Group(basePath)
		group.Use(anyAuth)
		{
			group.GET("", h.GetSettings)
			group.PUT("", h.UpdateSettings)
			group.POST("/notify/test", h.NotifyTest)
		}
	}
}
