import "server-only";

import { Redis } from "@upstash/redis";

type RateLimitDefinition = {
  key: string;
  limit: number;
  windowSeconds: number;
};

type RateLimitResult = {
  allowed: boolean;
  remaining: number;
  retryAfterSeconds: number;
};

type MemoryEntry = {
  count: number;
  resetAt: number;
};

const redis =
  process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN
    ? Redis.fromEnv()
    : null;

const memoryStore = globalThis as typeof globalThis & {
  __papereasyRateLimitStore__?: Map<string, MemoryEntry>;
};

if (!memoryStore.__papereasyRateLimitStore__) {
  memoryStore.__papereasyRateLimitStore__ = new Map<string, MemoryEntry>();
}

const localRateLimitStore = memoryStore.__papereasyRateLimitStore__;

async function checkRedisRateLimit(definition: RateLimitDefinition): Promise<RateLimitResult> {
  if (!redis) {
    throw new Error("Redis is not configured.");
  }

  const created = await redis.set(definition.key, 1, {
    ex: definition.windowSeconds,
    nx: true,
  });

  let count = 1;
  if (created === null) {
    count = await redis.incr(definition.key);
  }

  const ttl = await redis.ttl(definition.key);
  const retryAfterSeconds = Math.max(
    1,
    typeof ttl === "number" ? ttl : definition.windowSeconds,
  );

  return {
    allowed: count <= definition.limit,
    remaining: Math.max(0, definition.limit - count),
    retryAfterSeconds,
  };
}

function checkLocalRateLimit(definition: RateLimitDefinition): RateLimitResult {
  const now = Date.now();
  const entry = localRateLimitStore.get(definition.key);

  if (!entry || entry.resetAt <= now) {
    localRateLimitStore.set(definition.key, {
      count: 1,
      resetAt: now + definition.windowSeconds * 1000,
    });

    return {
      allowed: true,
      remaining: definition.limit - 1,
      retryAfterSeconds: definition.windowSeconds,
    };
  }

  entry.count += 1;
  localRateLimitStore.set(definition.key, entry);

  return {
    allowed: entry.count <= definition.limit,
    remaining: Math.max(0, definition.limit - entry.count),
    retryAfterSeconds: Math.max(1, Math.ceil((entry.resetAt - now) / 1000)),
  };
}

export async function enforceRateLimit(definition: RateLimitDefinition) {
  return redis ? checkRedisRateLimit(definition) : checkLocalRateLimit(definition);
}

export async function acquireDistributedLock(key: string, ttlSeconds: number) {
  if (!redis) {
    const existing = localRateLimitStore.get(key);
    const now = Date.now();
    if (existing && existing.resetAt > now) {
      return false;
    }

    localRateLimitStore.set(key, {
      count: 1,
      resetAt: now + ttlSeconds * 1000,
    });
    return true;
  }

  const result = await redis.set(key, "1", { nx: true, ex: ttlSeconds });
  return result === "OK";
}

export async function releaseDistributedLock(key: string) {
  if (!redis) {
    localRateLimitStore.delete(key);
    return;
  }

  await redis.del(key);
}
