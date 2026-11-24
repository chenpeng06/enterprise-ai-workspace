// Package ratelimit 提供基于 Redis Lua 的分布式令牌桶。
package ratelimit

import (
	"context"
	"fmt"
	"math"
	"time"

	"github.com/redis/go-redis/v9"
)

// Result 是一次令牌桶判定结果。
type Result struct {
	Allowed    bool
	Remaining  int
	RetryAfter time.Duration
}

// Limiter 使用 Redis Hash 保存 tokens/ts，Lua 保证读取-补充-扣减原子性。
type Limiter struct {
	client   *redis.Client
	capacity int
	refill   float64
	script   *redis.Script
	ttl      time.Duration
}

// allowScript:
// KEYS[1] bucket key
// ARGV[1] capacity, ARGV[2] refill/sec, ARGV[3] now(seconds float), ARGV[4] ttl(seconds)
// 返回 {allowed, remaining, retry_after_ms}
var allowScript = redis.NewScript(`
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(bucket[1])
local ts = tonumber(bucket[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end
if now > ts then
  tokens = math.min(capacity, tokens + (now - ts) * refill)
end

local allowed = 0
local retry_ms = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_ms = math.ceil(((1 - tokens) / refill) * 1000)
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, math.ceil(ttl * 1000))
return {allowed, math.floor(tokens), retry_ms}
`)

func New(client *redis.Client, capacity int, refillPerSecond float64) *Limiter {
	if capacity < 1 {
		capacity = 1
	}
	if refillPerSecond <= 0 {
		refillPerSecond = 0.5
	}
	ttl := time.Duration(math.Ceil(float64(capacity)/refillPerSecond)+60) * time.Second
	return &Limiter{
		client:   client,
		capacity: capacity,
		refill:   refillPerSecond,
		script:   allowScript,
		ttl:      ttl,
	}
}

// Allow 对 key 尝试获取一个令牌。Redis 故障由调用方决定 fail-open/fail-closed。
func (l *Limiter) Allow(ctx context.Context, key string) (Result, error) {
	if l == nil || l.client == nil {
		return Result{}, fmt.Errorf("rate limiter 未初始化")
	}
	now := float64(time.Now().UnixNano()) / float64(time.Second)
	raw, err := l.script.Run(
		ctx,
		l.client,
		[]string{key},
		l.capacity,
		l.refill,
		now,
		l.ttl.Seconds(),
	).Slice()
	if err != nil {
		return Result{}, err
	}
	if len(raw) != 3 {
		return Result{}, fmt.Errorf("rate limiter 返回格式错误")
	}

	allowed, _ := raw[0].(int64)
	remaining, _ := raw[1].(int64)
	retryMS, _ := raw[2].(int64)
	return Result{
		Allowed:    allowed == 1,
		Remaining:  int(remaining),
		RetryAfter: time.Duration(retryMS) * time.Millisecond,
	}, nil
}
