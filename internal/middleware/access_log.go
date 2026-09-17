// Package middleware provides HTTP middleware for the Gin engine.
package middleware

import (
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// 静态资源前缀：命中则降级为 Debug 级别，避免刷屏
var accessLogQuietPrefixes = []string{
	"/_next/",
	"/static/",
	"/favicon.ico",
	"/logo.png",
}

// AccessLog 记录每个 HTTP 请求的结构化访问日志。
//
// 记录内容包含 Origin / Referer，用于在前后端分离或经代理访问时定位
// “请求到底打到了哪个 origin”这类问题。出于安全考虑，不记录
// Authorization、Cookie 等凭据类请求头。
func AccessLog(logger *zap.Logger) gin.HandlerFunc {
	// zap.NewDevelopment() 默认给 Warn 及以上附加调用栈，会让每个 4xx
	// 都输出一大段无意义的堆栈。这里把栈阈值抬到 Error，仅 5xx 才带栈。
	log := logger.WithOptions(zap.AddStacktrace(zapcore.ErrorLevel))

	return func(c *gin.Context) {
		start := time.Now()

		c.Next()

		latency := time.Since(start)
		status := c.Writer.Status()
		path := c.Request.URL.Path

		fields := []zap.Field{
			zap.String("method", c.Request.Method),
			zap.String("path", path),
			zap.Int("status", status),
			zap.Duration("latency", latency),
			zap.String("client_ip", c.ClientIP()),
			zap.String("origin", c.Request.Header.Get("Origin")),
			zap.String("referer", c.Request.Header.Get("Referer")),
			zap.Int("body_size", c.Writer.Size()),
		}

		if q := c.Request.URL.RawQuery; q != "" {
			fields = append(fields, zap.String("query", q))
		}
		if ua := c.Request.Header.Get("User-Agent"); ua != "" {
			fields = append(fields, zap.String("user_agent", truncate(ua, 120)))
		}
		if errMsg := c.Errors.ByType(gin.ErrorTypeAny); len(errMsg) > 0 {
			fields = append(fields, zap.String("gin_errors", errMsg.String()))
		}

		switch {
		case status >= 500:
			log.Error("HTTP", fields...)
		case status >= 400:
			log.Warn("HTTP", fields...)
		case isQuietPath(path):
			log.Debug("HTTP", fields...)
		default:
			log.Info("HTTP", fields...)
		}
	}
}

func isQuietPath(path string) bool {
	for _, prefix := range accessLogQuietPrefixes {
		if strings.HasPrefix(path, prefix) {
			return true
		}
	}
	// 带扩展名的静态文件（js/css/png/mp4 等）同样视为静态资源
	if i := strings.LastIndex(path, "/"); i >= 0 {
		path = path[i+1:]
	}
	return strings.Contains(path, ".")
}

func truncate(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[:max] + "..."
}
