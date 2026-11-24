package middleware

import (
	"log/slog"
	"time"

	"github.com/gin-gonic/gin"
)

// AccessLog 输出结构化访问日志，后续将在此处接入 TTFT 与 Token 统计。
func AccessLog(logger *slog.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		startedAt := time.Now()
		c.Next()
		latency := time.Since(startedAt)

		requestID, _ := c.Get(ContextRequestID)
		attributes := []any{
			"method", c.Request.Method,
			"path", c.Request.URL.Path,
			"status", c.Writer.Status(),
			"latency_ms", float64(latency.Microseconds()) / 1000.0,
			"client_ip", c.ClientIP(),
			"request_id", requestID,
		}
		if len(c.Errors) > 0 {
			attributes = append(attributes, "errors", c.Errors.String())
		}

		switch {
		case c.Writer.Status() >= 500:
			logger.Error("http_request", attributes...)
		case c.Writer.Status() >= 400:
			logger.Warn("http_request", attributes...)
		default:
			logger.Info("http_request", attributes...)
		}
	}
}
