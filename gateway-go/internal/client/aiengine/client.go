// Package aiengine 封装对 Python AI 引擎的内部调用。
// Phase 1 只提供健康检查与契约版本校验；Phase 3 将在此基础上实现 SSE 透传代理。
package aiengine

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const maxHealthBodyBytes = 1 << 20

type Client struct {
	baseURL    string
	token      string
	httpClient *http.Client
}

func New(baseURL, token string, timeout time.Duration) *Client {
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		token:   token,
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}

type HealthCheck struct {
	Status    string   `json:"status"`
	LatencyMS *float64 `json:"latency_ms"`
	Message   *string  `json:"message"`
}

type Health struct {
	Status          string                 `json:"status"`
	Service         string                 `json:"service"`
	Version         string                 `json:"version"`
	ContractVersion string                 `json:"contract_version"`
	Checks          map[string]HealthCheck `json:"checks"`
}

// Health 调用 GET /internal/v1/health。
func (c *Client) Health(ctx context.Context) (*Health, error) {
	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		c.baseURL+"/internal/v1/health",
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("构造 AI 引擎健康检查请求失败: %w", err)
	}
	request.Header.Set("Accept", "application/json")
	request.Header.Set("X-Internal-Token", c.token)

	response, err := c.httpClient.Do(request)
	if err != nil {
		return nil, fmt.Errorf("请求 AI 引擎失败: %w", err)
	}
	defer func() {
		_ = response.Body.Close()
	}()

	body, err := io.ReadAll(io.LimitReader(response.Body, maxHealthBodyBytes))
	if err != nil {
		return nil, fmt.Errorf("读取 AI 引擎响应失败: %w", err)
	}
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf(
			"AI 引擎健康检查返回 HTTP %d: %s",
			response.StatusCode,
			truncate(string(body), 300),
		)
	}

	var health Health
	if err := json.Unmarshal(body, &health); err != nil {
		return nil, fmt.Errorf("解析 AI 引擎健康检查响应失败: %w", err)
	}
	return &health, nil
}

func truncate(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[:limit] + "..."
}
