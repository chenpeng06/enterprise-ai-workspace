package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/joho/godotenv"

	"github.com/enterprise-ai-workspace/gateway-go/internal/cache"
	"github.com/enterprise-ai-workspace/gateway-go/internal/client/aiengine"
	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/httpserver"
	"github.com/enterprise-ai-workspace/gateway-go/internal/observability"
	"github.com/enterprise-ai-workspace/gateway-go/internal/store"
)

// version 由构建参数注入：-ldflags "-X main.version=<git sha>"。
var version = "dev"

func main() {
	if err := run(); err != nil {
		slog.Error("gateway 启动失败", "error", err)
		os.Exit(1)
	}
}

func run() error {
	// .env 可选：容器环境直接注入环境变量即可。
	_ = godotenv.Load()

	cfg, err := config.Load()
	if err != nil {
		return fmt.Errorf("加载配置失败: %w", err)
	}
	if version == "dev" && cfg.Version != "" {
		version = cfg.Version
	}

	logger := observability.NewLogger(cfg.LogLevel, cfg.Env)
	slog.SetDefault(logger)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	postgres, err := store.NewPostgres(ctx, cfg.DatabaseURL, cfg.DBMaxConns)
	if err != nil {
		return err
	}
	defer postgres.Close()

	redisClient, err := cache.NewRedis(cfg.RedisAddr, cfg.RedisPassword, cfg.RedisDB)
	if err != nil {
		return err
	}
	defer func() {
		if closeErr := redisClient.Close(); closeErr != nil {
			logger.Warn("关闭 Redis 客户端失败", "error", closeErr)
		}
	}()

	engineClient := aiengine.New(cfg.AIEngineBaseURL, cfg.InternalToken, cfg.AIEngineTimeout)

	server := httpserver.New(cfg, logger, httpserver.Dependencies{
		DB:       postgres,
		Redis:    redisClient,
		AIEngine: engineClient,
		Version:  version,
	})

	serverErr := make(chan error, 1)
	go func() {
		serverErr <- server.ListenAndServe()
	}()
	logger.Info("gateway 已启动", "addr", cfg.HTTPAddr, "env", cfg.Env, "version", version)

	select {
	case <-ctx.Done():
		logger.Info("收到退出信号，开始优雅停机")
	case err := <-serverErr:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			return fmt.Errorf("HTTP 服务异常退出: %w", err)
		}
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("优雅停机失败: %w", err)
	}

	logger.Info("gateway 已停止")
	return nil
}
