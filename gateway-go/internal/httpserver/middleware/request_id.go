package middleware

import (
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

const (
	HeaderRequestID  = "X-Request-Id"
	ContextRequestID = "request_id"
)

// RequestID 复用合法入站请求 ID，或生成新的 UUID；同时回写响应头。
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		requestID := strings.TrimSpace(c.GetHeader(HeaderRequestID))
		if _, err := uuid.Parse(requestID); err != nil {
			requestID = uuid.NewString()
		}

		c.Set(ContextRequestID, requestID)
		c.Header(HeaderRequestID, requestID)
		c.Next()
	}
}
