package config

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	defaultInternalToken = "dev-internal-token-change-me"
	defaultDatabaseURL   = "postgres://workspace:workspace@127.0.0.1:5432/workspace?sslmode=disable"
)

// Config 是网关的全部启动配置，全部来自环境变量（支持 .env 文件）。
type Config struct {
	Env     string
	Version string

	HTTPAddr          string
	ReadHeaderTimeout time.Duration
	WriteTimeout      time.Duration
	IdleTimeout       time.Duration
	ShutdownTimeout   time.Duration

	AIEngineBaseURL string
	AIEngineTimeout time.Duration
	InternalToken   string

	DatabaseURL string
	DBMaxConns  int32

	RedisAddr     string
	RedisPassword string
	RedisDB       int

	LogLevel    string
	CORSOrigins []string
}

// Load 读取并校验配置。任何非法值都会在启动阶段直接失败（fail fast）。
func Load() (*Config, error) {
	readHeaderTimeout, err := durationEnv("HTTP_READ_HEADER_TIMEOUT", 10*time.Second)
	if err != nil {
		return nil, err
	}
	writeTimeout, err := durationEnv("HTTP_WRITE_TIMEOUT", 0)
	if err != nil {
		return nil, err
	}
	idleTimeout, err := durationEnv("HTTP_IDLE_TIMEOUT", 120*time.Second)
	if err != nil {
		return nil, err
	}
	shutdownTimeout, err := durationEnv("SHUTDOWN_TIMEOUT", 15*time.Second)
	if err != nil {
		return nil, err
	}
	engineTimeout, err := durationEnv("AI_ENGINE_TIMEOUT", 5*time.Second)
	if err != nil {
		return nil, err
	}

	if readHeaderTimeout <= 0 {
		return nil, fmt.Errorf("HTTP_READ_HEADER_TIMEOUT 必须大于 0")
	}
	if writeTimeout < 0 {
		return nil, fmt.Errorf("HTTP_WRITE_TIMEOUT 不能为负数（SSE 场景建议为 0）")
	}
	if idleTimeout <= 0 {
		return nil, fmt.Errorf("HTTP_IDLE_TIMEOUT 必须大于 0")
	}
	if shutdownTimeout <= 0 {
		return nil, fmt.Errorf("SHUTDOWN_TIMEOUT 必须大于 0")
	}
	if engineTimeout <= 0 {
		return nil, fmt.Errorf("AI_ENGINE_TIMEOUT 必须大于 0")
	}

	dbMaxConns, err := intEnv("DB_MAX_CONNS", 10, 1, 100)
	if err != nil {
		return nil, err
	}
	redisDB, err := intEnv("REDIS_DB", 0, 0, 15)
	if err != nil {
		return nil, err
	}

	cfg := &Config{
		Env:               strings.TrimSpace(getEnv("APP_ENV", "development")),
		Version:           strings.TrimSpace(getEnv("APP_VERSION", "dev")),
		HTTPAddr:          strings.TrimSpace(getEnv("HTTP_ADDR", ":8080")),
		ReadHeaderTimeout: readHeaderTimeout,
		WriteTimeout:      writeTimeout,
		IdleTimeout:       idleTimeout,
		ShutdownTimeout:   shutdownTimeout,
		AIEngineBaseURL:   strings.TrimRight(strings.TrimSpace(getEnv("AI_ENGINE_BASE_URL", "http://127.0.0.1:8000")), "/"),
		AIEngineTimeout:   engineTimeout,
		InternalToken:     strings.TrimSpace(getEnv("INTERNAL_TOKEN", defaultInternalToken)),
		DatabaseURL:       strings.TrimSpace(getEnv("DATABASE_URL", defaultDatabaseURL)),
		DBMaxConns:        int32(dbMaxConns),
		RedisAddr:         strings.TrimSpace(getEnv("REDIS_ADDR", "127.0.0.1:6379")),
		RedisPassword:     os.Getenv("REDIS_PASSWORD"),
		RedisDB:           redisDB,
		LogLevel:          strings.ToLower(strings.TrimSpace(getEnv("LOG_LEVEL", "info"))),
		CORSOrigins:       splitCSV(getEnv("CORS_ORIGINS", "http://127.0.0.1:5173")),
	}

	switch cfg.Env {
	case "development", "staging", "production":
	default:
		return nil, fmt.Errorf("APP_ENV 必须是 development/staging/production，当前为 %q", cfg.Env)
	}
	switch cfg.LogLevel {
	case "debug", "info", "warn", "error":
	default:
		return nil, fmt.Errorf("LOG_LEVEL 必须是 debug/info/warn/error，当前为 %q", cfg.LogLevel)
	}
	if cfg.HTTPAddr == "" {
		return nil, fmt.Errorf("HTTP_ADDR 不能为空")
	}
	if cfg.AIEngineBaseURL == "" {
		return nil, fmt.Errorf("AI_ENGINE_BASE_URL 不能为空")
	}
	engineURL, err := url.Parse(cfg.AIEngineBaseURL)
	if err != nil || (engineURL.Scheme != "http" && engineURL.Scheme != "https") || engineURL.Host == "" {
		return nil, fmt.Errorf("AI_ENGINE_BASE_URL 必须是合法的 http(s) 地址，当前为 %q", cfg.AIEngineBaseURL)
	}
	if cfg.DatabaseURL == "" {
		return nil, fmt.Errorf("DATABASE_URL 不能为空")
	}
	if cfg.RedisAddr == "" {
		return nil, fmt.Errorf("REDIS_ADDR 不能为空")
	}
	if cfg.Env == "production" && (cfg.InternalToken == defaultInternalToken || len(cfg.InternalToken) < 32) {
		return nil, fmt.Errorf("生产环境的 INTERNAL_TOKEN 必须替换默认值且长度不小于 32")
	}

	return cfg, nil
}

func getEnv(key, fallback string) string {
	if value, ok := os.LookupEnv(key); ok && strings.TrimSpace(value) != "" {
		return value
	}
	return fallback
}

func durationEnv(key string, fallback time.Duration) (time.Duration, error) {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback, nil
	}
	value, err := time.ParseDuration(raw)
	if err != nil {
		return 0, fmt.Errorf("环境变量 %s 不是合法的 duration（如 10s、2m）: %w", key, err)
	}
	return value, nil
}

func intEnv(key string, fallback, minValue, maxValue int) (int, error) {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil {
		return 0, fmt.Errorf("环境变量 %s 必须是整数: %w", key, err)
	}
	if value < minValue || value > maxValue {
		return 0, fmt.Errorf("环境变量 %s 必须在 [%d, %d] 范围内，当前为 %d", key, minValue, maxValue, value)
	}
	return value, nil
}

func splitCSV(raw string) []string {
	parts := strings.Split(raw, ",")
	result := make([]string, 0, len(parts))
	for _, part := range parts {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			result = append(result, trimmed)
		}
	}
	return result
}
