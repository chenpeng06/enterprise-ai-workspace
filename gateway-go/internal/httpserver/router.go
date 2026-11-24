package httpserver

import (
	"log/slog"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"

	"github.com/enterprise-ai-workspace/gateway-go/internal/admin"
	"github.com/enterprise-ai-workspace/gateway-go/internal/auth"
	"github.com/enterprise-ai-workspace/gateway-go/internal/chatproxy"
	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/documents"
	"github.com/enterprise-ai-workspace/gateway-go/internal/httpserver/middleware"
	"github.com/enterprise-ai-workspace/gateway-go/internal/quota"
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

	var authRedisClient *redis.Client
	if redisClient != nil {
		authRedisClient = redisClient.Client
	}
	authService := auth.New(cfg, deps.DB, authRedisClient)
	authHandler := auth.NewHandler(authService)
	adminHandler := admin.NewHandler(cfg, deps.DB)
	quotaService := quota.New(cfg, deps.DB, authRedisClient)
	documentsHandler := documents.New(cfg, deps.DB, deps.AIEngine)

	api := router.Group("/api/v1")
	{
		// 公开接口：登录与演示元信息。其余业务接口必须登录。
		api.POST("/auth/login", authHandler.Login)
		api.POST("/auth/logout", authHandler.Logout)
		api.GET("/bootstrap", chat.Bootstrap)

		protected := api.Group("")
		protected.Use(auth.RequireAuth(authService))
		{
			protected.GET("/auth/me", authHandler.Me)
			protected.GET("/auth/quota", quotaService.StatusHandler)
			protected.GET("/agent-types", adminHandler.PublicAgentTypes)
			protected.GET(
				"/chunks/:chunk_id",
				auth.RequirePermission(auth.PermissionDocsRead),
				chat.Chunk,
			)
			protected.GET(
				"/admin/metrics",
				auth.RequirePermission(auth.PermissionMetrics),
				chat.Metrics,
			)
			protected.GET(
				"/documents",
				auth.RequirePermission(auth.PermissionDocsRead),
				documentsHandler.List,
			)
			protected.POST(
				"/documents",
				auth.RequirePermission(auth.PermissionDocsWrite),
				documentsHandler.Upload,
			)

			chatRoute := protected.Group("")
			if limiter != nil {
				chatRoute.Use(ratelimit.Middleware(limiter, cfg, logger, deps.DB))
			}
			chatRoute.Use(quota.Middleware(quotaService))
			chatRoute.POST("/chat/stream", chat.Stream)

			adminGroup := protected.Group("/admin")
			adminGroup.Use(auth.RequirePermission(auth.PermissionUsersRead))
			{
				adminGroup.GET("/users", adminHandler.ListUsers)
				adminGroup.GET("/settings", adminHandler.GetSettings)
				adminGroup.GET("/agent-types", adminHandler.GetAgentTypes)
				adminGroup.PUT(
					"/agent-types",
					auth.RequirePermission(auth.PermissionAgents),
					adminHandler.PutAgentTypes,
				)
				adminGroup.PUT(
					"/settings/guest-quota",
					auth.RequirePermission(auth.PermissionQuota),
					adminHandler.UpdateGuestQuota,
				)

				adminWrite := adminGroup.Group("")
				adminWrite.Use(auth.RequirePermission(auth.PermissionUsersEdit))
				adminWrite.POST("/users", adminHandler.CreateUser)
				adminWrite.PATCH("/users/:user_id/role", adminHandler.UpdateRole)
				adminWrite.DELETE("/users/:user_id", adminHandler.RemoveUser)
				adminWrite.POST("/users/:user_id/reset-password", adminHandler.ResetPassword)
			}
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
