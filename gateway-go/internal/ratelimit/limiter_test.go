package ratelimit

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

func TestLimiterConsumesAndRejects(t *testing.T) {
	client := redis.NewClient(&redis.Options{Addr: "127.0.0.1:6379"})
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := client.Ping(ctx).Err(); err != nil {
		t.Skipf("Redis 不可用，跳过分布式限流测试: %v", err)
	}
	t.Cleanup(func() { _ = client.Close() })

	limiter := New(client, 2, 0.001)
	key := fmt.Sprintf("test:ratelimit:%s", uuid.NewString())
	t.Cleanup(func() {
		cleanupCtx, cleanupCancel := context.WithTimeout(context.Background(), time.Second)
		defer cleanupCancel()
		_ = client.Del(cleanupCtx, key).Err()
	})

	first, err := limiter.Allow(ctx, key)
	if err != nil {
		t.Fatalf("首次 Allow 失败: %v", err)
	}
	if !first.Allowed || first.Remaining != 1 {
		t.Fatalf("首次令牌桶结果不符合预期: %+v", first)
	}

	second, err := limiter.Allow(ctx, key)
	if err != nil {
		t.Fatalf("第二次 Allow 失败: %v", err)
	}
	if !second.Allowed || second.Remaining != 0 {
		t.Fatalf("第二次令牌桶结果不符合预期: %+v", second)
	}

	third, err := limiter.Allow(ctx, key)
	if err != nil {
		t.Fatalf("第三次 Allow 失败: %v", err)
	}
	if third.Allowed {
		t.Fatalf("配额耗尽后仍被放行: %+v", third)
	}
	if third.RetryAfter <= 0 {
		t.Fatalf("拒绝时必须给出 RetryAfter，实际为 %v", third.RetryAfter)
	}
}
