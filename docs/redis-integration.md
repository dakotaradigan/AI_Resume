# How Redis Hooks Into This App

A walkthrough of the Redis integration, written as a reference for wiring the
same pattern into other projects. The app runs identically with or without
Redis — that dual-backend design is the interesting part.

## The one switch: `REDIS_URL`

Everything keys off a single env var. Unset → in-memory Python dicts
(per-process, reset on restart — the everyday dev mode). Set → shared Redis
state that survives restarts and works across multiple instances.

```
REDIS_URL=redis://default:password@host:port
```

On Railway: add the Redis plugin to the project, and it injects `REDIS_URL`
into the service environment automatically. Nothing else to configure.

## Where the connection is made

`backend/main.py`, `get_session_store()`:

```python
redis_client = redis_asyncio.from_url(
    redis_url,
    encoding="utf-8",
    decode_responses=True,      # str in/out instead of bytes
    health_check_interval=30,   # ping stale pooled connections
)
_session_store = SessionStore(redis_client=redis_client, session_ttl=...)
```

Key points:

- `redis.asyncio` (bundled with `redis>=5`) gives an asyncio-native client —
  no thread pools, awaits compose with FastAPI handlers.
- The import is guarded (`try: from redis import asyncio ...`) so the package
  is optional until `REDIS_URL` is actually set.
- One client, created lazily once, holds an internal connection pool. The
  FastAPI shutdown hook calls `store.close()`.

## The dual-backend pattern

`SessionStore` methods all follow the same shape:

```python
async def something(self, ...):
    if self._redis is not None:
        ...redis path...
        return
    async with self._lock:
        ...in-memory path...
```

The in-memory path is guarded by one `asyncio.Lock` (single event loop —
cheap). The Redis path relies on Redis's own atomicity instead. Every feature
must be implemented on BOTH sides, which keeps you honest about what state the
feature actually needs.

What each feature maps to in Redis:

| Feature | Redis structure | Why |
|---|---|---|
| Chat history | `LIST` (`RPUSH`/`LRANGE`) per session, `EXPIRE` for TTL | Ordered append-only turns |
| Session/visitor metadata (quota count, unlimited flag) | `HASH` per identity | Multiple small fields updated together |
| Rate limits | `INCR` on a time-bucketed key + `EXPIRE` | Fixed-window counter in two commands |
| Daily budget / JD budget | Lua script: GET → compare → `INCR` | Check-and-increment must be one atomic step |

## Why the Lua scripts

The subtle bugs live in read-modify-write races. Two requests both read
`count=1`, both see it under the limit, both increment → limit exceeded.
In-memory, the asyncio lock prevents this. In Redis, a small Lua script runs
atomically server-side:

```lua
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current >= tonumber(ARGV[1]) then return 0 end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], 259200)
return 1
```

See `check_and_increment_limit` (per-visitor chat quota, on a HASH),
`check_and_increment_scoped_limit` (JD daily budget), and
`reserve_daily_conversation`/`release_daily_conversation` (global daily cap,
reserve-before-call with release on failure) in `backend/main.py`.

## Key design habits worth copying

1. **Prefix every key** (`resume-assistant:session:...`) so one Redis instance
   can be shared without collisions and keys are greppable in `redis-cli`.
2. **TTL everything** (`EXPIRE` on each write). No cron cleanup, no unbounded
   growth; the in-memory backend needs an explicit `cleanup_expired()` sweep
   instead — that asymmetry is the price of the fallback.
3. **Time-bucketed rate-limit keys** (`key:{epoch // window}`) turn "sliding
   window-ish" limiting into a plain counter.
4. **Fail visible**: if `REDIS_URL` is set but the package is missing, raise
   at startup rather than silently degrading to per-process state.

## Verifying it live

```bash
# 1. Point at Redis and boot
REDIS_URL=redis://... uvicorn main:app
# 2. Chat once, then inspect state
redis-cli --scan --pattern 'resume-assistant:*'
redis-cli HGETALL 'resume-assistant:session:<visitor-uuid>:meta'
# 3. Restart the app, chat again with the same visitor cookie:
#    the quota count must survive the restart (it won't without Redis).
```
