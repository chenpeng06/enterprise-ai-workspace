package config

import "testing"

func TestLoadDefaultsForDevelopment(t *testing.T) {
	t.Setenv("APP_ENV", "development")
	t.Setenv("INTERNAL_TOKEN", "")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() 返回错误: %v", err)
	}
	if cfg.HTTPAddr != ":8080" {
		t.Errorf("HTTPAddr = %q, want :8080", cfg.HTTPAddr)
	}
	if cfg.AIEngineBaseURL != "http://127.0.0.1:8000" {
		t.Errorf("AIEngineBaseURL = %q", cfg.AIEngineBaseURL)
	}
	if cfg.WriteTimeout != 0 {
		t.Errorf("WriteTimeout = %v, want 0（SSE 长连接）", cfg.WriteTimeout)
	}
}

func TestLoadRejectsWeakProductionToken(t *testing.T) {
	t.Setenv("APP_ENV", "production")
	t.Setenv("INTERNAL_TOKEN", "too-short")

	if _, err := Load(); err == nil {
		t.Fatal("生产环境弱 Token 应当被拒绝")
	}
}

func TestLoadRejectsInvalidDuration(t *testing.T) {
	t.Setenv("HTTP_READ_HEADER_TIMEOUT", "not-a-duration")

	if _, err := Load(); err == nil {
		t.Fatal("非法 duration 应当被拒绝")
	}
}
