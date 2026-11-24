package httpserver

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/enterprise-ai-workspace/gateway-go/internal/cache"
	"github.com/enterprise-ai-workspace/gateway-go/internal/client/aiengine"
	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/store"
)

type Dependencies struct {
	DB       *store.Postgres
	Redis    *cache.Redis
	AIEngine *aiengine.Client
	Version  string
}

type Server struct {
	logger     *slog.Logger
	httpServer *http.Server
}

func New(cfg *config.Config, logger *slog.Logger, deps Dependencies) *Server {
	return &Server{
		logger: logger,
		httpServer: &http.Server{
			Addr:              cfg.HTTPAddr,
			Handler:           NewRouter(cfg, logger, deps),
			ReadHeaderTimeout: cfg.ReadHeaderTimeout,
			// 0 表示禁用写超时：SSE 长连接不能设置全局 WriteTimeout，
			// 单条流的超时控制在 Phase 3 由代理层按事件空闲时间实现。
			WriteTimeout: cfg.WriteTimeout,
			IdleTimeout:  cfg.IdleTimeout,
			ErrorLog:     slog.NewLogLogger(logger.Handler(), slog.LevelError),
		},
	}
}

func (s *Server) ListenAndServe() error {
	s.logger.Info("HTTP 服务开始监听", "addr", s.httpServer.Addr)
	return s.httpServer.ListenAndServe()
}

func (s *Server) Shutdown(ctx context.Context) error {
	return s.httpServer.Shutdown(ctx)
}
