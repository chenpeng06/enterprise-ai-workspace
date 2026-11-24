package httpserver

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/enterprise-ai-workspace/gateway-go/internal/contract"
)

type DependencyCheck struct {
	Status    string   `json:"status"`
	LatencyMS *float64 `json:"latency_ms,omitempty"`
	Message   *string  `json:"message,omitempty"`
}

type HealthResponse struct {
	Status          string                     `json:"status"`
	Service         string                     `json:"service"`
	Version         string                     `json:"version"`
	ContractVersion string                     `json:"contract_version"`
	Time            time.Time                  `json:"time"`
	Checks          map[string]DependencyCheck `json:"checks,omitempty"`
}

type dependencyCheck struct {
	name string
	run  func(context.Context) error
}

func livenessHandler(deps Dependencies) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, HealthResponse{
			Status:          "ok",
			Service:         "gateway-go",
			Version:         deps.Version,
			ContractVersion: contract.Version,
			Time:            time.Now().UTC(),
		})
	}
}

func versionHandler(deps Dependencies) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"service":          "gateway-go",
			"version":          deps.Version,
			"contract_version": contract.Version,
		})
	}
}

// readinessHandler 并发探测 PostgreSQL、Redis 与 AI 引擎；
// 任一依赖不可用即返回 503，供 SLB / K8s readinessProbe 摘流。
func readinessHandler(logger *slog.Logger, deps Dependencies) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
		defer cancel()

		checks := []dependencyCheck{
			{
				name: "postgres",
				run: func(ctx context.Context) error {
					if deps.DB == nil {
						return errors.New("PostgreSQL 客户端未初始化")
					}
					return deps.DB.Ping(ctx)
				},
			},
			{
				name: "redis",
				run: func(ctx context.Context) error {
					if deps.Redis == nil {
						return errors.New("Redis 客户端未初始化")
					}
					return deps.Redis.Ping(ctx)
				},
			},
			{
				name: "ai_engine",
				run: func(ctx context.Context) error {
					if deps.AIEngine == nil {
						return errors.New("AI 引擎客户端未初始化")
					}
					health, err := deps.AIEngine.Health(ctx)
					if err != nil {
						return err
					}
					if health.ContractVersion != contract.Version {
						return fmt.Errorf(
							"契约版本不匹配: engine=%s gateway=%s",
							health.ContractVersion,
							contract.Version,
						)
					}
					if health.Status == "down" {
						return errors.New("AI 引擎自检状态为 down")
					}
					return nil
				},
			},
		}

		results := runDependencyChecks(ctx, checks)
		status := "ok"
		statusCode := http.StatusOK
		for _, result := range results {
			if result.Status != "ok" {
				status = "degraded"
				statusCode = http.StatusServiceUnavailable
				break
			}
		}
		if statusCode != http.StatusOK {
			logger.Warn("readiness_degraded", "checks", len(results))
		}

		c.JSON(statusCode, HealthResponse{
			Status:          status,
			Service:         "gateway-go",
			Version:         deps.Version,
			ContractVersion: contract.Version,
			Time:            time.Now().UTC(),
			Checks:          results,
		})
	}
}

func runDependencyChecks(ctx context.Context, checks []dependencyCheck) map[string]DependencyCheck {
	results := make(map[string]DependencyCheck, len(checks))
	var mutex sync.Mutex
	var waitGroup sync.WaitGroup

	for _, check := range checks {
		check := check
		waitGroup.Add(1)
		go func() {
			defer waitGroup.Done()

			startedAt := time.Now()
			err := check.run(ctx)
			latencyMS := float64(time.Since(startedAt).Microseconds()) / 1000.0

			mutex.Lock()
			defer mutex.Unlock()

			if err != nil {
				message := err.Error()
				results[check.name] = DependencyCheck{
					Status:    "down",
					LatencyMS: &latencyMS,
					Message:   &message,
				}
				return
			}
			results[check.name] = DependencyCheck{
				Status:    "ok",
				LatencyMS: &latencyMS,
			}
		}()
	}

	waitGroup.Wait()
	return results
}
