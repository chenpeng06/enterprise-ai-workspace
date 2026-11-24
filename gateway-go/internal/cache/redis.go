package cache

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

// Redis 持有 go-redis 客户端；Redis 同时用于分布式令牌桶与限流日志缓冲。
type Redis struct {
	Client *redis.Client
}

func NewRedis(addr, password string, db int) (*Redis, error) {
	if addr == "" {
		return nil, fmt.Errorf("REDIS_ADDR 不能为空")
	}

	client := redis.NewClient(&redis.Options{
		Addr:         addr,
		Password:     password,
		DB:           db,
		DialTimeout:  3 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
		PoolSize:     20,
		MinIdleConns: 2,
	})

	return &Redis{Client: client}, nil
}

func (r *Redis) Ping(ctx context.Context) error {
	if r == nil || r.Client == nil {
		return fmt.Errorf("Redis 客户端未初始化")
	}
	return r.Client.Ping(ctx).Err()
}

func (r *Redis) Close() error {
	if r == nil || r.Client == nil {
		return nil
	}
	return r.Client.Close()
}
