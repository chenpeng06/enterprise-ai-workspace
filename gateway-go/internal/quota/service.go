package quota

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"

	"github.com/enterprise-ai-workspace/gateway-go/internal/auth"
	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/store"
)

type Service struct {
	cfg   *config.Config
	store *store.Postgres
	redis *redis.Client
}

type Status struct {
	Limit     int       `json:"limit"`
	Used      int       `json:"used"`
	Remaining int       `json:"remaining"`
	ResetAt   time.Time `json:"reset_at"`
}

var consumeScript = redis.NewScript(`
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local used = tonumber(redis.call('GET', key) or '0')
if used >= limit then
  return {0, used, ttl}
end
used = redis.call('INCR', key)
if used == 1 then
  redis.call('PEXPIRE', key, ttl)
end
return {1, used, ttl}
`)

func New(cfg *config.Config, database *store.Postgres, redisClient *redis.Client) *Service {
	return &Service{cfg: cfg, store: database, redis: redisClient}
}

func (s *Service) Limit(ctx context.Context, workspaceID string) (int, error) {
	settings, err := s.store.WorkspaceSettings(ctx, workspaceID)
	if err != nil {
		return 0, err
	}
	if raw, ok := settings["guest_daily_query_quota"]; ok {
		switch value := raw.(type) {
		case float64:
			return int(value), nil
		case int:
			return value, nil
		}
	}
	return s.cfg.GuestQuotaDefault, nil
}

func (s *Service) Consume(
	ctx context.Context,
	workspaceID, userID string,
	limit int,
) (allowed bool, used int, resetAt time.Time, err error) {
	if s.redis == nil {
		return false, 0, time.Time{}, fmt.Errorf("Redis 未初始化")
	}
	now := time.Now().In(shanghai())
	resetAt = nextReset(now)
	key := fmt.Sprintf("guestquota:%s:%s:%s", workspaceID, userID, now.Format("20060102"))
	ttl := time.Until(resetAt)
	if ttl <= 0 {
		ttl = 24 * time.Hour
	}
	raw, err := consumeScript.Run(ctx, s.redis, []string{key}, limit, ttl.Milliseconds()).Slice()
	if err != nil {
		return false, 0, resetAt, fmt.Errorf("游客配额计数失败: %w", err)
	}
	if len(raw) != 3 {
		return false, 0, resetAt, fmt.Errorf("游客配额返回格式错误")
	}
	allowedValue, _ := raw[0].(int64)
	usedValue, _ := raw[1].(int64)
	return allowedValue == 1, int(usedValue), resetAt, nil
}

func (s *Service) Status(
	ctx context.Context,
	workspaceID, userID string,
	limit int,
) (Status, error) {
	now := time.Now().In(shanghai())
	key := fmt.Sprintf("guestquota:%s:%s:%s", workspaceID, userID, now.Format("20060102"))
	used := 0
	if s.redis != nil {
		value, err := s.redis.Get(ctx, key).Int()
		if err != nil && !errors.Is(err, redis.Nil) {
			return Status{}, fmt.Errorf("读取游客配额失败: %w", err)
		}
		used = value
	}
	remaining := limit - used
	if remaining < 0 {
		remaining = 0
	}
	return Status{Limit: limit, Used: used, Remaining: remaining, ResetAt: nextReset(now)}, nil
}

// Middleware 只对 viewer 生效；配额在 LLM 调用前扣减。
func Middleware(service *Service) gin.HandlerFunc {
	return func(c *gin.Context) {
		identity, ok := auth.IdentityFromContext(c)
		if !ok {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": gin.H{
				"code": "unauthorized", "message": "请先登录", "retryable": false,
			}})
			return
		}
		if identity.Role != "viewer" {
			c.Next()
			return
		}
		limit, err := service.Limit(c.Request.Context(), identity.WorkspaceID)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
				"code": "dependency_unavailable", "message": "游客配额配置不可用", "retryable": true,
			}})
			return
		}
		allowed, used, resetAt, err := service.Consume(
			c.Request.Context(), identity.WorkspaceID, identity.UserID, limit,
		)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
				"code": "dependency_unavailable", "message": "游客配额服务不可用", "retryable": true,
			}})
			return
		}
		remaining := limit - used
		if remaining < 0 {
			remaining = 0
		}
		c.Header("X-Guest-Quota-Limit", fmt.Sprintf("%d", limit))
		c.Header("X-Guest-Quota-Remaining", fmt.Sprintf("%d", remaining))
		if !allowed {
			retryAfter := time.Until(resetAt)
			if retryAfter < 0 {
				retryAfter = time.Second
			}
			c.Header("Retry-After", fmt.Sprintf("%d", int(math.Ceil(retryAfter.Seconds()))))
			requestID := c.GetString("request_id")
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": gin.H{
				"code":           "guest_quota_exceeded",
				"message":        "游客今日检索次数已用完，请明日再试或联系管理员",
				"retryable":      true,
				"retry_after_ms": retryAfter.Milliseconds(),
				"request_id":     requestID,
				"quota": gin.H{
					"limit": limit, "used": used, "remaining": 0,
					"reset_at": resetAt.UTC(),
				},
			}})
			return
		}
		c.Set("guest_quota", Status{
			Limit: limit, Used: used, Remaining: remaining, ResetAt: resetAt,
		})
		c.Next()
	}
}

func shanghai() *time.Location {
	location, err := time.LoadLocation("Asia/Shanghai")
	if err != nil {
		return time.FixedZone("CST", 8*3600)
	}
	return location
}

func nextReset(now time.Time) time.Time {
	location := now.Location()
	return time.Date(now.Year(), now.Month(), now.Day()+1, 0, 5, 0, 0, location)
}
