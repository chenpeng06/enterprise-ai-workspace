package httpserver

import (
	"log/slog"
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/httpserver/middleware"
)

// NewRouter 注册网关基础路由。Phase 3 将在此挂载：
//   - /api/v1/auth、/api/v1/documents、/api/v1/admin 等业务接口
//   - Redis 令牌桶限流中间件
//   - /api/v1/chat/stream 的 SSE 透传代理
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
