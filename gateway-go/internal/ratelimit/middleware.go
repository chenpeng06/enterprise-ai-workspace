package ratelimit

import (
	"context"
	"log/slog"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
)

// AuditEvent 是限流拦截的落库事件。
type AuditEvent struct {
	WorkspaceID  string
	UserID       string
	Route        string
	Scope        string
	LimitValue   int
	Observed     int
	RetryAfterMS int
	ClientIP     string
}

// Auditor 由 store.Postgres 实现。
type Auditor interface {
	LogRateLimit(ctx context.Context, event AuditEvent) error
}

// Middleware 以 workspace + 路由 + 用户/IP 为桶维度；Redis 故障时 fail-open。
func Middleware(
	limiter *Limiter,
	cfg *config.Config,
	logger *slog.Logger,
	auditor Auditor,
) gin.HandlerFunc {
	return func(c *gin.Context) {
		workspaceID := c.GetString("auth_workspace_id")
		userID := c.GetString("auth_user_id")
		if workspaceID == "" {
			workspaceID = strings.TrimSpace(c.GetHeader("X-Workspace-Id"))
		}
		if userID == "" {
			userID = strings.TrimSpace(c.GetHeader("X-User-Id"))
		}
		if workspaceID == "" {
			workspaceID = cfg.DevWorkspaceID
		}
		identity := userID
		if identity == "" {
			identity = c.ClientIP()
		}
		route := c.FullPath()
		if route == "" {
			route = c.Request.URL.Path
		}
		key := "ratelimit:" + workspaceID + ":" + route + ":" + identity

		ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
		result, err := limiter.Allow(ctx, key)
		cancel()
		if err != nil {
			logger.Warn("限流器不可用，fail-open", "error", err, "key", key)
			c.Next()
			return
		}

		remaining := result.Remaining
		c.Header("X-RateLimit-Limit", strconv.Itoa(cfg.RateLimitCapacity))
		c.Header("X-RateLimit-Remaining", strconv.Itoa(max(remaining, 0)))
		if result.Allowed {
			c.Next()
			return
		}

		retryAfter := result.RetryAfter
		if retryAfter <= 0 {
			retryAfter = time.Second
		}
		retrySeconds := int(math.Ceil(retryAfter.Seconds()))
		c.Header("Retry-After", strconv.Itoa(retrySeconds))
		c.Header("X-RateLimit-Retry-After", strconv.Itoa(retrySeconds))

		if auditor != nil {
			event := AuditEvent{
				WorkspaceID:  workspaceID,
				UserID:       userID,
				Route:        route,
				Scope:        "workspace",
				LimitValue:   cfg.RateLimitCapacity,
				Observed:     cfg.RateLimitCapacity + 1,
				RetryAfterMS: int(retryAfter.Milliseconds()),
				ClientIP:     c.ClientIP(),
			}
			go func() {
				auditCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
				defer cancel()
				if auditErr := auditor.LogRateLimit(auditCtx, event); auditErr != nil {
					logger.Warn("写入限流日志失败", "error", auditErr)
				}
			}()
		}

		requestID, _ := c.Get("request_id")
		c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
			"error": gin.H{
				"code":           "rate_limited",
				"message":        "请求过于频繁，请稍后重试",
				"retryable":      true,
				"retry_after_ms": retryAfter.Milliseconds(),
				"request_id":     requestID,
			},
		})
	}
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
