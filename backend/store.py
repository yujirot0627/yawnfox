# app/store.py
"""
Redis-backed shared state for Yawnfox signaling / matchmaking.

All cross-instance state (the waiting pool, partner mapping and presence) lives
in Redis so the backend can run as several horizontally-scaled instances.

The only per-process state is the live WebSocket objects themselves (they cannot
be serialized). Any instance can still deliver a message to any client through
Redis pub/sub: see `route()` and `pubsub_listener()`.

Connection:
    Uses redis-py over a TLS (rediss://) connection so that pub/sub works.
    Configure with UPSTASH_REDIS_URL (+ optional UPSTASH_REDIS_TOKEN); see
    `_build_url()` and backend/.env.example.
"""
import os
import json
import time
import uuid
import asyncio
import logging
from typing import Optional, Callable, Awaitable, Iterable

import redis.asyncio as redis
from redis.exceptions import RedisError

logger = logging.getLogger("yawnfox.store")

# --- Keys / config ---
PREFIX = "yf"
WAITING_KEY = f"{PREFIX}:waiting"           # ZSET: member=ws_id, score=enqueue_ms
WAKEUP_CHANNEL = f"{PREFIX}:wakeup"         # matcher wakeup fan-out
CHAN_PREFIX = f"{PREFIX}:chan:"             # per-client delivery channel prefix
CHAN_PATTERN = f"{CHAN_PREFIX}*"
MATCHER_LOCK_KEY = f"{PREFIX}:matcher:lock"
MATCHER_LOCK_MS = 5000

CONN_TTL = int(os.environ.get("CONN_TTL", "90"))            # presence key ttl (s)
PARTNER_TTL = int(os.environ.get("PARTNER_TTL", "300"))     # partner mapping ttl (s)
TOPICS_TTL = int(os.environ.get("TOPICS_TTL", "1800"))      # waiting topics ttl (s)

RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_MAX", "5"))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))  # seconds


def conn_key(ws_id: str) -> str:
    return f"{PREFIX}:conn:{ws_id}"


def partner_key(ws_id: str) -> str:
    return f"{PREFIX}:partner:{ws_id}"


def topics_key(ws_id: str) -> str:
    return f"{PREFIX}:topics:{ws_id}"


def chan_key(ws_id: str) -> str:
    return f"{CHAN_PREFIX}{ws_id}"


def rate_key(ip: str) -> str:
    return f"{PREFIX}:rl:{ip}"


# --- Module state ---
_redis: Optional[redis.Redis] = None
_pubsub = None
_instance_id: str = os.environ.get("FLY_MACHINE_ID") or uuid.uuid4().hex
_local_delivery: Optional[Callable[[str, str], Awaitable[bool]]] = None
_on_wakeup: Optional[Callable[[], None]] = None


# --- Lua scripts (run atomically inside Redis) ---
_RATE_LIMIT_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local maxc = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= maxc then
  return 0
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window)
return 1
"""

# Atomically remove BOTH waiting members or neither (prevents orphaning a user
# who was popped from the queue but never paired).
_POP_PAIR_LUA = """
local sa = redis.call('ZSCORE', KEYS[1], ARGV[1])
local sb = redis.call('ZSCORE', KEYS[1], ARGV[2])
if sa and sb then
  redis.call('ZREM', KEYS[1], ARGV[1], ARGV[2])
  return 1
end
return 0
"""

# Release the matcher lock only if we still own it.
_RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

# Atomically read + delete a pairing in BOTH directions. Returns the former
# partner id (or false). Atomicity means simultaneous disconnects can't double
# notify or leave a dangling reverse-mapping. ARGV[1] = partner key prefix.
_CLEAR_PARTNER_LUA = """
local p = redis.call('GET', KEYS[1])
if p then
  redis.call('DEL', KEYS[1])
  redis.call('DEL', ARGV[1] .. p)
  return p
end
return false
"""


def instance_id() -> str:
    return _instance_id


def set_local_delivery(cb: Callable[[str, str], Awaitable[bool]]) -> None:
    """Register the per-process delivery callback (ws_id, text) -> delivered?."""
    global _local_delivery
    _local_delivery = cb


def set_wakeup_callback(cb: Callable[[], None]) -> None:
    """Register a callback used to wake this instance's matcher loop."""
    global _on_wakeup
    _on_wakeup = cb


def _build_url() -> str:
    """Resolve the Redis connection URL from the environment.

    Accepts either a full redis:// / rediss:// URL in UPSTASH_REDIS_URL, or a
    bare host in UPSTASH_REDIS_URL combined with UPSTASH_REDIS_TOKEN as the
    password (assembled into a TLS rediss:// URL on port 6379). Falls back to
    REDIS_URL (or localhost) for local development.
    """
    url = (os.environ.get("UPSTASH_REDIS_URL") or "").strip()
    token = (os.environ.get("UPSTASH_REDIS_TOKEN") or "").strip()
    if url:
        if url.startswith("redis://") or url.startswith("rediss://"):
            return url
        host = url.replace("https://", "").replace("http://", "").strip("/")
        if token:
            return f"rediss://default:{token}@{host}:6379"
        return f"rediss://{host}:6379"
    return (os.environ.get("REDIS_URL") or "redis://localhost:6379").strip()


async def connect() -> bool:
    """Open the Redis connection. Returns True on success (never raises)."""
    global _redis
    url = _build_url()
    try:
        _redis = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
            retry_on_timeout=True,
        )
        await _redis.ping()
        logger.info(f"Connected to Redis ({url.rsplit('@', 1)[-1]}) as instance {_instance_id}")
        return True
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        _redis = None
        return False


def is_ready() -> bool:
    return _redis is not None


async def close() -> None:
    global _redis, _pubsub
    for obj in (_pubsub, _redis):
        if obj is None:
            continue
        try:
            await obj.aclose()
        except AttributeError:
            try:
                await obj.close()
            except Exception:
                pass
        except Exception:
            pass
    _redis = None
    _pubsub = None


# --- Presence -------------------------------------------------------------

async def register_connection(ws_id: str) -> None:
    if not _redis:
        return
    try:
        await _redis.set(conn_key(ws_id), _instance_id, ex=CONN_TTL)
    except RedisError as e:
        logger.warning(f"register_connection failed: {e}")


async def unregister_connection(ws_id: str) -> None:
    if not _redis:
        return
    try:
        await _redis.delete(conn_key(ws_id))
    except RedisError as e:
        logger.warning(f"unregister_connection failed: {e}")


async def is_connected(ws_id: str) -> bool:
    if not _redis:
        return False
    try:
        return bool(await _redis.exists(conn_key(ws_id)))
    except RedisError:
        return False


async def refresh(ws_ids: Iterable[str]) -> None:
    """Heartbeat: extend TTLs for this instance's live clients."""
    if not _redis:
        return
    ids = list(ws_ids)
    if not ids:
        return
    try:
        pipe = _redis.pipeline(transaction=False)
        for wid in ids:
            pipe.expire(conn_key(wid), CONN_TTL)
            pipe.expire(partner_key(wid), PARTNER_TTL)
            pipe.expire(topics_key(wid), TOPICS_TTL)
        await pipe.execute()
    except RedisError as e:
        logger.warning(f"refresh failed: {e}")


# --- Waiting pool ---------------------------------------------------------

async def enqueue_waiting(ws_id: str, topics: Iterable[str]) -> None:
    if not _redis:
        return
    now_ms = int(time.time() * 1000)
    norm = [t for t in topics if t]
    try:
        pipe = _redis.pipeline(transaction=True)
        pipe.zadd(WAITING_KEY, {ws_id: now_ms})
        pipe.delete(topics_key(ws_id))
        if norm:
            pipe.sadd(topics_key(ws_id), *norm)
            pipe.expire(topics_key(ws_id), TOPICS_TTL)
        await pipe.execute()
    except RedisError as e:
        logger.warning(f"enqueue_waiting failed: {e}")


async def remove_waiting(ws_id: str) -> None:
    if not _redis:
        return
    try:
        pipe = _redis.pipeline(transaction=False)
        pipe.zrem(WAITING_KEY, ws_id)
        pipe.delete(topics_key(ws_id))
        await pipe.execute()
    except RedisError as e:
        logger.warning(f"remove_waiting failed: {e}")


async def waiting_count() -> int:
    if not _redis:
        return 0
    try:
        return int(await _redis.zcard(WAITING_KEY))
    except RedisError:
        return 0


# --- Partner mapping ------------------------------------------------------

async def set_partners(a: str, b: str) -> None:
    if not _redis:
        return
    try:
        pipe = _redis.pipeline(transaction=True)
        pipe.set(partner_key(a), b, ex=PARTNER_TTL)
        pipe.set(partner_key(b), a, ex=PARTNER_TTL)
        await pipe.execute()
    except RedisError as e:
        logger.warning(f"set_partners failed: {e}")


async def get_partner(ws_id: str) -> Optional[str]:
    if not _redis:
        return None
    try:
        return await _redis.get(partner_key(ws_id))
    except RedisError:
        return None


async def clear_partner(ws_id: str) -> Optional[str]:
    """Unpair ws_id (both directions) atomically. Returns the former partner id."""
    if not _redis:
        return None
    try:
        partner = await _redis.eval(
            _CLEAR_PARTNER_LUA, 1, partner_key(ws_id), f"{PREFIX}:partner:"
        )
        return partner or None
    except RedisError as e:
        logger.warning(f"clear_partner failed: {e}")
        return None


# --- Delivery (local first, else cross-instance via pub/sub) --------------

async def route(target_ws_id: str, message: dict) -> None:
    """Deliver `message` to a client that may be on any instance."""
    text = json.dumps(message)
    if _local_delivery is not None:
        try:
            if await _local_delivery(target_ws_id, text):
                return
        except Exception as e:
            logger.warning(f"local delivery error: {e}")
    if not _redis:
        return
    try:
        await _redis.publish(chan_key(target_ws_id), text)
    except RedisError as e:
        logger.warning(f"publish failed: {e}")


# --- Matcher --------------------------------------------------------------

async def trigger_wakeup() -> None:
    """Wake the local matcher immediately and nudge the other instances."""
    if _on_wakeup:
        _on_wakeup()
    if not _redis:
        return
    try:
        await _redis.publish(WAKEUP_CHANNEL, "1")
    except RedisError:
        pass


async def try_acquire_matcher_lock() -> bool:
    if not _redis:
        return False
    try:
        return bool(await _redis.set(MATCHER_LOCK_KEY, _instance_id, nx=True, px=MATCHER_LOCK_MS))
    except RedisError:
        return False


async def release_matcher_lock() -> None:
    if not _redis:
        return
    try:
        await _redis.eval(_RELEASE_LOCK_LUA, 1, MATCHER_LOCK_KEY, _instance_id)
    except RedisError:
        pass


async def _pop_pair(a: str, b: str) -> bool:
    try:
        return await _redis.eval(_POP_PAIR_LUA, 1, WAITING_KEY, a, b) == 1
    except RedisError:
        return False


async def _topics(ws_id: str) -> set:
    try:
        return await _redis.smembers(topics_key(ws_id)) or set()
    except RedisError:
        return set()


async def run_matcher_rounds(max_rounds: int = 200) -> None:
    """Form pairs while at least two waiting clients remain.

    Mirrors the original in-memory algorithm: oldest waiter first (fairness),
    prefer a topic overlap, otherwise fall back to the longest-waiting peer.
    The caller is expected to hold the matcher lock; `_pop_pair` additionally
    guarantees atomicity so a lock expiry can never double-match or orphan.
    """
    if not _redis:
        return
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        try:
            waiting = await _redis.zrange(WAITING_KEY, 0, -1)  # oldest first
        except RedisError as e:
            logger.warning(f"zrange failed: {e}")
            return
        if len(waiting) < 2:
            return

        candidate_a = waiting[0]
        if not await is_connected(candidate_a):
            await remove_waiting(candidate_a)
            continue

        topics_a = await _topics(candidate_a)
        best_match = None
        first_alive = None

        for other in waiting[1:]:
            if not await is_connected(other):
                await remove_waiting(other)
                continue
            if first_alive is None:
                first_alive = other
            if not topics_a:
                break  # no topic preference -> longest-waiting peer is enough
            if topics_a & await _topics(other):
                best_match = other
                break

        if best_match is None:
            best_match = first_alive
        if best_match is None:
            return  # only ghosts besides candidate_a

        if not await _pop_pair(candidate_a, best_match):
            continue  # lost a race; re-read the pool

        try:
            await _redis.delete(topics_key(candidate_a), topics_key(best_match))
        except RedisError:
            pass
        await set_partners(candidate_a, best_match)
        logger.info(f"Match formed: {candidate_a} <> {best_match}")
        await route(candidate_a, {"name": "PARTNER_FOUND", "data": "GO_FIRST"})
        await route(best_match, {"name": "PARTNER_FOUND", "data": "WAIT"})


# --- Rate limiting --------------------------------------------------------

async def check_rate_limit(ip: str) -> bool:
    """Sliding-window limiter (per IP). Returns True if the connection is allowed.

    Fails open (allows the connection) when Redis is unavailable so an outage
    never locks every user out.
    """
    if not _redis:
        return True
    now_ms = int(time.time() * 1000)
    member = f"{now_ms}-{uuid.uuid4().hex[:8]}"
    try:
        result = await _redis.eval(
            _RATE_LIMIT_LUA, 1, rate_key(ip),
            now_ms, RATE_LIMIT_WINDOW * 1000, RATE_LIMIT_MAX, member,
        )
        return result == 1
    except RedisError as e:
        logger.warning(f"rate limit check failed (fail-open): {e}")
        return True


# --- Pub/Sub listener -----------------------------------------------------

async def pubsub_listener() -> None:
    """Background task: deliver cross-instance messages and matcher wakeups.

    Uses a single pattern subscription (`yf:chan:*`) so connections never have
    to (un)subscribe individually; each instance simply ignores channels for
    clients it does not own. Reconnects with backoff on failure.
    """
    global _pubsub
    backoff = 0.5
    while True:
        if not _redis:
            await asyncio.sleep(1.0)
            continue
        try:
            _pubsub = _redis.pubsub(ignore_subscribe_messages=True)
            await _pubsub.psubscribe(CHAN_PATTERN)
            await _pubsub.subscribe(WAKEUP_CHANNEL)
            logger.info("Pub/Sub listener subscribed.")
            backoff = 0.5
            while True:
                msg = await _pubsub.get_message(timeout=5.0)
                if msg is None:
                    continue
                if msg.get("type") not in ("message", "pmessage"):
                    continue
                channel = msg.get("channel")
                data = msg.get("data")
                if channel == WAKEUP_CHANNEL:
                    if _on_wakeup:
                        _on_wakeup()
                    continue
                if channel and channel.startswith(CHAN_PREFIX) and data is not None:
                    ws_id = channel[len(CHAN_PREFIX):]
                    if _local_delivery is not None:
                        try:
                            await _local_delivery(ws_id, data)
                        except Exception as e:
                            logger.warning(f"pubsub local delivery failed: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"pubsub listener error, reconnecting: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)
        finally:
            # R3: always close the old PubSub before reconnecting (or on exit)
            # so repeated reconnects don't leak connections.
            if _pubsub is not None:
                try:
                    await _pubsub.aclose()
                except Exception:
                    pass
                _pubsub = None
