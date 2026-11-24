package observability

import (
	"log/slog"
	"os"
	"strings"
)

// NewLogger 输出结构化日志：开发环境用 text，便于人读；预发/生产用 JSON，便于采集。
func NewLogger(level, env string) *slog.Logger {
	var slogLevel slog.Level
	switch strings.ToLower(level) {
	case "debug":
		slogLevel = slog.LevelDebug
	case "warn":
		slogLevel = slog.LevelWarn
	case "error":
		slogLevel = slog.LevelError
	default:
		slogLevel = slog.LevelInfo
	}

	options := &slog.HandlerOptions{
		Level:     slogLevel,
		AddSource: slogLevel == slog.LevelDebug,
	}

	var handler slog.Handler
	if env == "development" {
		handler = slog.NewTextHandler(os.Stdout, options)
	} else {
		handler = slog.NewJSONHandler(os.Stdout, options)
	}

	return slog.New(handler).With(
		"service", "gateway-go",
		"env", env,
	)
}
