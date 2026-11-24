package store

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Postgres 持有 pgx 连接池。构造时只解析配置，不强制建连，
// 因此数据库暂时不可用时网关仍可启动，并由 /readyz 暴露降级状态。
type Postgres struct {
	Pool *pgxpool.Pool
}

func NewPostgres(ctx context.Context, databaseURL string, maxConns int32) (*Postgres, error) {
	poolConfig, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("解析 DATABASE_URL 失败: %w", err)
	}

	poolConfig.MaxConns = maxConns
	poolConfig.MinConns = 0
	poolConfig.MaxConnIdleTime = 5 * time.Minute
	poolConfig.MaxConnLifetime = 30 * time.Minute
	poolConfig.HealthCheckPeriod = 30 * time.Second

	pool, err := pgxpool.NewWithConfig(ctx, poolConfig)
	if err != nil {
		return nil, fmt.Errorf("创建 PostgreSQL 连接池失败: %w", err)
	}

	return &Postgres{Pool: pool}, nil
}

func (p *Postgres) Ping(ctx context.Context) error {
	if p == nil || p.Pool == nil {
		return fmt.Errorf("PostgreSQL 连接池未初始化")
	}
	return p.Pool.Ping(ctx)
}

func (p *Postgres) Close() {
	if p == nil || p.Pool == nil {
		return
	}
	p.Pool.Close()
}
