package httpserver

import (
	"log/slog"
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/enterprise-ai-workspace/gateway-go/internal/chatproxy"
	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/httpserver/middleware"
	"github.com/enterprise-ai-workspace/gateway-go/internal/ratelimit"
)

// NewRouter 注册网关路由：
//   - /api/v1/chat/stream：Redis 令牌桶 + SSE 透传/指标采集
//   - /api/v1/chunks/:id：原文预览
//   - /api/v1/admin/metrics：监控看板
func NewRouter(cfg *config.Config, logger *slog.Logger, deps Dependencies) *gin.Engine {
	if cfg.Env != "development" {
		gin.SetMode(gin.ReleaseMode)
	}

	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(middleware.RequestID())
	router.Use(middleware.AccessLog(logger))

	router.GET("/healthz", livenessHandler(deps))
	router.GET("/readyz", readinessHandler(logger, deps))
	router.GET("/version", versionHandler(deps))

	var redisClient = deps.Redis
	var limiter *ratelimit.Limiter
	if redisClient != nil {
		limiter = ratelimit.New(
			redisClient.Client,
			cfg.RateLimitCapacity,
			cfg.RateLimitRefillPerSecond,
		)
	}
	chat := chatproxy.New(cfg, logger, deps.DB, deps.AIEngine)

	api := router.Group("/api/v1")
	{
		api.GET("/bootstrap", chat.Bootstrap)
		api.GET("/chunks/:chunk_id", chat.Chunk)
		api.GET("/admin/metrics", chat.Metrics)
		if limiter != nil {
			api.POST(
				"/chat/stream",
				ratelimit.Middleware(limiter, cfg, logger, deps.DB),
				chat.Stream,
			)
		} else {
			// 基础设施降级时仍允许对话，但生产 readiness 已会失败。
			api.POST("/chat/stream", chat.Stream)
		}
	}

	router.NoRoute(func(c *gin.Context) {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{
				"code":    "not_found",
				"message": "路由不存在",
			},
		})
	})

	return router
}
