# app/store.py
"""
Redis-backed shared state for Yawnfox signaling / matchmaking.

All cross-instance state (the waiting pool, partner mapping and presence) lives
in Redis so the backend can run as several horizontally-scaled instances.

The only per-process state is the live WebSocket objects themselves (they cannot
be serialized). Any instance can still deliver a message to any client through
Redis pub/sub: see `route()` and `pubsub_listener()`.

In-memory mode (REDIS_URL not set):
    All state is kept in plain Python dicts within this process. No Redis
    connection is attempted and no error is logged. Single-instance only;
    suitable for local development and zero-config deployments.

Connection (Redis mode):
    Uses redis-py over a TLS (rediss://) connection so that pub/sub works.
    Configure with REDIS_URL (+ optional UPSTASH_REDIS_TOKEN); see
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
# Long enough that a realistic worst-case pass finishes inside it: 200 pairings x
# (1 EVAL + 1 set_partners + 2 publishes) ~= 800 round-trips ~= 4s at Upstash RTT,
# which was a coin flip against the previous 5000. Not refreshed mid-pass — the
# lock is only a throughput optimisation now that _MATCH_LUA is atomic, and
# run_matcher_rounds stops itself at 80% of this rather than outlive it.
MATCHER_LOCK_MS = 15000

# Only the head of the waiting queue can ever be matched, so the matcher reads a
# bounded window of it instead of the whole pool. This bounds *topic search
# quality*, never liveness: the fallback always pairs the two oldest live clients,
# so nobody starves behind a window they cannot see past.
MATCH_WINDOW = 64

# How long the pub/sub link may stay silent before we make it prove it is alive.
# Only a *hung* server needs this: one that drops the socket raises out of
# get_message immediately and for free. That case is rare, so the probe is
# deliberately infrequent — at 30s it cost 8,640 commands/day on an idle
# instance, most of the Upstash free tier, to watch for something that usually
# announces itself. Lower it if you would rather find a hung Redis sooner than
# save the commands. Costs nothing on a busy instance: traffic is its own proof.
HEALTH_PING_SECONDS = int(os.environ.get("HEALTH_PING_SECONDS", "120"))
HEALTH_PING_TIMEOUT = 5

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
# Two variables, deliberately: _client is the redis-py client object, built once
# and kept for the life of the process; _redis is that same object only while the
# connection is known to work, and None otherwise. Everything else in this module
# guards on `if not _redis`, so health is enforced in one place and an outage
# short-circuits every operation instead of blocking on a dead socket. See
# _set_redis_up() for who flips it.
_client: Optional[redis.Redis] = None
_redis: Optional[redis.Redis] = None
_pubsub = None
_instance_id: str = os.environ.get("FLY_MACHINE_ID") or uuid.uuid4().hex
_local_delivery: Optional[Callable[[str, str], Awaitable[bool]]] = None
_on_wakeup: Optional[Callable[[], None]] = None

# In-memory mode: active when REDIS_URL is not configured.
# Redis code is kept intact for future horizontal scaling.
_inmemory_mode: bool = not bool((os.environ.get("REDIS_URL") or "").strip())

# In-memory state (used only when _inmemory_mode is True)
_mem_waiting: dict = {}        # ws_id -> enqueue_ms
_mem_partners: dict = {}       # ws_id -> partner_ws_id (stored both directions)
_mem_topics: dict = {}         # ws_id -> set[str]
_mem_connections: set = set()  # registered ws_ids
_mem_matcher_locked: bool = False


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

# Form ONE pair, atomically, in one command.
#
# This used to be a read-scan-pop dance in Python: ZRANGE the whole waiting pool,
# then an EXISTS and (when the head client had topics) a SMEMBERS per candidate,
# sequentially. At 5000 waiting that is a 5000-member payload plus up to ~10,000
# sequential round-trips per round. Here the window read, the liveness filter, the
# topic preference and the pop all happen inside Redis, so a pairing costs one
# billed command whatever the pool depth.
#
# Selection semantics are unchanged from that Python version: the oldest live
# waiter is the candidate (fairness), preferring the first peer sharing a topic,
# otherwise falling back to the longest-waiting live peer.
#
# Popping both members here also makes the pop atomic by construction, which is
# what _POP_PAIR_LUA used to buy separately — two instances racing can no longer
# double-match or orphan a waiter, only duplicate work.
_MATCH_LUA = """
local prefix = ARGV[1]
local window = tonumber(ARGV[2])
local ids = redis.call('ZRANGE', KEYS[1], 0, window - 1)   -- oldest first
local live = {}
for i = 1, #ids do
  if redis.call('EXISTS', prefix .. 'conn:' .. ids[i]) == 1 then
    live[#live + 1] = ids[i]
  else
    redis.call('ZREM', KEYS[1], ids[i])
    redis.call('DEL', prefix .. 'topics:' .. ids[i])
  end
end
if #live < 2 then
  -- Ghosts were just evicted, so live members may sit past the window. Say so
  -- rather than reporting the pool exhausted, or a block of >= window dead
  -- entries at the head would wedge matching permanently.
  if #live < #ids then return {'RETRY'} end
  return {}
end
local a = live[1]
local best = live[2]                       -- fallback: longest-waiting live peer
local ta = redis.call('SMEMBERS', prefix .. 'topics:' .. a)
if #ta > 0 then
  local want = {}
  for i = 1, #ta do want[ta[i]] = true end
  for i = 2, #live do
    local t = redis.call('SMEMBERS', prefix .. 'topics:' .. live[i])
    local hit = false
    for j = 1, #t do
      if want[t[j]] then hit = true break end
    end
    if hit then best = live[i] break end
  end
end
redis.call('ZREM', KEYS[1], a, best)
redis.call('DEL', prefix .. 'topics:' .. a, prefix .. 'topics:' .. best)
return {a, best}
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

# Extend every TTL this instance is responsible for, in ONE command.
# The previous version pipelined three EXPIREs per client. Two of those usually
# targeted keys that do not exist — a client that is neither paired nor queued has
# no partner or topics key — so they were billed and did nothing. Calls made from
# inside a script are not billed separately, so a single EVAL removes that waste
# and makes the heartbeat cost independent of how many clients are connected.
# Keys are built from the prefix rather than declared in KEYS, the same approach
# _CLEAR_PARTNER_LUA already takes; effect replication makes that safe.
_REFRESH_LUA = """
local prefix = ARGV[1]
local conn_ttl = tonumber(ARGV[2])
local partner_ttl = tonumber(ARGV[3])
local topics_ttl = tonumber(ARGV[4])
for i = 5, #ARGV do
  local id = ARGV[i]
  redis.call('EXPIRE', prefix .. 'conn:' .. id, conn_ttl)
  redis.call('EXPIRE', prefix .. 'partner:' .. id, partner_ttl)
  redis.call('EXPIRE', prefix .. 'topics:' .. id, topics_ttl)
end
return #ARGV - 4
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

    Accepts either a full redis:// / rediss:// URL in REDIS_URL, or a bare host
    in REDIS_URL combined with UPSTASH_REDIS_TOKEN as the password (assembled
    into a TLS rediss:// URL on port 6379).
    """
    url = (os.environ.get("REDIS_URL") or "").strip()
    token = (os.environ.get("UPSTASH_REDIS_TOKEN") or "").strip()
    if url:
        if url.startswith("redis://") or url.startswith("rediss://"):
            return url
        host = url.replace("https://", "").replace("http://", "").strip("/")
        if token:
            return f"rediss://default:{token}@{host}:6379"
        return f"rediss://{host}:6379"
    # Not reachable in practice: an empty REDIS_URL selects in-memory mode, so
    # connect() returns before it ever calls this. Kept as a safe default.
    return "redis://localhost:6379"


async def connect() -> bool:
    """Open the Redis connection. Returns True on success (never raises).

    When REDIS_URL is not set, skips Redis entirely and runs in
    in-memory mode; always returns True without logging any error.
    """
    global _client
    if _inmemory_mode:
        logger.info(f"REDIS_URL not set — in-memory mode (instance {_instance_id})")
        return True
    url = _build_url()
    try:
        _client = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
            retry_on_timeout=True,
        )
    except Exception as e:
        # A URL we cannot even parse will not fix itself, so leave _client unset
        # and let the pub/sub listener idle rather than retry forever.
        logger.error(f"Redis client could not be created: {e}")
        return False
    try:
        await _client.ping()
    except Exception as e:
        # Keep the client. from_url() does not connect, so this failure says
        # nothing about the URL — and holding on to it is what lets the pub/sub
        # listener retry and bring us up on its own once Redis is reachable.
        # Previously this dropped the client, and nothing ever rebuilt it: an
        # instance that booted during a blip stayed dead until someone restarted it.
        logger.error(f"Redis connection failed: {e} — starting in redis-down mode")
        return False
    _set_redis_up(True)
    logger.info(f"Connected to Redis ({url.rsplit('@', 1)[-1]}) as instance {_instance_id}")
    return True


def _set_redis_up(up: bool) -> None:
    """Mark the Redis connection usable or not. Logs only on a transition.

    The pub/sub listener is the only caller: it holds a long-lived connection
    that redis-py already PINGs every health_check_interval, so it learns about a
    failure without anyone spending a command to ask.
    """
    global _redis
    was_up = _redis is not None
    _redis = _client if up else None
    if up and not was_up:
        logger.info("Redis connection restored — accepting clients again")
    elif was_up and not up:
        logger.error("Redis connection lost — refusing new clients until it returns")


def is_ready() -> bool:
    """Can this instance accept traffic?

    True in in-memory mode, and in Redis mode only while the connection is up —
    tracked continuously, not just at startup, so an outage that begins later
    turns this False and new clients are told SERVER_UNAVAILABLE instead of
    waiting in a pool that is not there.

    This is deliberately NOT a statement about Redis — it answers "should we let a
    client in", which is why it is true with no Redis at all. Use mode() to find
    out how state is actually being stored.
    """
    return _inmemory_mode or _redis is not None


def mode() -> str:
    """How shared state is stored right now. Reported by /ping.

    "in-memory"  REDIS_URL is unset. No Redis is contacted; state lives in this
                 process. Single instance only, and the rate limiter is disabled.
    "redis"      Connected. Multi-instance safe.
    "redis-down" REDIS_URL is set but the connection is not usable right now —
                 it failed at startup or dropped since — so the instance is
                 refusing clients. Recovers on its own; no restart needed.

    is_ready() collapses the first two into one boolean, which is what made a
    misnamed REDIS_URL look healthy. This does not.
    """
    if _inmemory_mode:
        return "in-memory"
    return "redis" if _redis is not None else "redis-down"


async def close() -> None:
    global _client, _redis, _pubsub
    if _inmemory_mode:
        return
    for obj in (_pubsub, _client):
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
    _client = None
    _redis = None
    _pubsub = None


# --- Presence -------------------------------------------------------------

async def register_connection(ws_id: str) -> None:
    if _inmemory_mode:
        _mem_connections.add(ws_id)
        return
    if not _redis:
        return
    try:
        await _redis.set(conn_key(ws_id), _instance_id, ex=CONN_TTL)
    except RedisError as e:
        logger.warning(f"register_connection failed: {e}")


async def unregister_connection(ws_id: str) -> None:
    if _inmemory_mode:
        _mem_connections.discard(ws_id)
        return
    if not _redis:
        return
    try:
        await _redis.delete(conn_key(ws_id))
    except RedisError as e:
        logger.warning(f"unregister_connection failed: {e}")


async def is_connected(ws_id: str) -> bool:
    if _inmemory_mode:
        return ws_id in _mem_connections
    if not _redis:
        return False
    try:
        return bool(await _redis.exists(conn_key(ws_id)))
    except RedisError:
        return False


async def refresh(ws_ids: Iterable[str]) -> None:
    """Heartbeat: extend TTLs for this instance's live clients.

    One EVAL for the whole batch, whatever the client count — see _REFRESH_LUA.
    """
    if _inmemory_mode:
        return  # no TTLs to refresh in in-memory mode
    if not _redis:
        return
    ids = list(ws_ids)
    if not ids:
        return
    try:
        await _redis.eval(
            _REFRESH_LUA, 0, f"{PREFIX}:", CONN_TTL, PARTNER_TTL, TOPICS_TTL, *ids
        )
    except RedisError as e:
        logger.warning(f"refresh failed: {e}")


# --- Waiting pool ---------------------------------------------------------

async def enqueue_waiting(ws_id: str, topics: Iterable[str]) -> None:
    if _inmemory_mode:
        _mem_waiting[ws_id] = int(time.time() * 1000)
        _mem_topics[ws_id] = {t for t in topics if t}
        return
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
    if _inmemory_mode:
        _mem_waiting.pop(ws_id, None)
        _mem_topics.pop(ws_id, None)
        return
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
    if _inmemory_mode:
        return len(_mem_waiting)
    if not _redis:
        return 0
    try:
        return int(await _redis.zcard(WAITING_KEY))
    except RedisError:
        return 0


# --- Partner mapping ------------------------------------------------------

async def set_partners(a: str, b: str) -> None:
    if _inmemory_mode:
        _mem_partners[a] = b
        _mem_partners[b] = a
        return
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
    if _inmemory_mode:
        return _mem_partners.get(ws_id)
    if not _redis:
        return None
    try:
        return await _redis.get(partner_key(ws_id))
    except RedisError:
        return None


async def clear_partner(ws_id: str) -> Optional[str]:
    """Unpair ws_id (both directions) atomically. Returns the former partner id."""
    if _inmemory_mode:
        partner = _mem_partners.pop(ws_id, None)
        if partner:
            _mem_partners.pop(partner, None)
        return partner
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
    global _mem_matcher_locked
    if _inmemory_mode:
        # Single-instance: simple flag prevents re-entrance within one event loop.
        if _mem_matcher_locked:
            return False
        _mem_matcher_locked = True
        return True
    if not _redis:
        return False
    try:
        return bool(await _redis.set(MATCHER_LOCK_KEY, _instance_id, nx=True, px=MATCHER_LOCK_MS))
    except RedisError:
        return False


async def release_matcher_lock() -> None:
    global _mem_matcher_locked
    if _inmemory_mode:
        _mem_matcher_locked = False
        return
    if not _redis:
        return
    try:
        await _redis.eval(_RELEASE_LOCK_LUA, 1, MATCHER_LOCK_KEY, _instance_id)
    except RedisError:
        pass


async def run_matcher_rounds(max_rounds: int = 200) -> bool:
    """Form pairs while at least two waiting clients remain.

    Each round is one _MATCH_LUA call, which does the selection and the pop
    atomically. The caller is expected to hold the matcher lock, but correctness
    no longer depends on it: losing the lock mid-pass can only duplicate work.

    Returns True if it stopped with work possibly remaining (deadline, round
    cap, or ghosts evicted past the window), so the caller can go again rather
    than wait out MATCH_POLL_SECONDS.
    """
    if _inmemory_mode:
        return await _run_matcher_rounds_inmemory(max_rounds)
    if not _redis:
        return False
    # Stop before the lock we hold can expire under us, rather than spending a
    # command per round to refresh it.
    deadline = time.monotonic() + MATCHER_LOCK_MS / 1000 * 0.8
    for _ in range(max_rounds):
        if time.monotonic() > deadline:
            return True
        try:
            pair = await _redis.eval(
                _MATCH_LUA, 1, WAITING_KEY, f"{PREFIX}:", MATCH_WINDOW
            )
        except RedisError as e:
            logger.warning(f"match eval failed: {e}")
            return False
        if not pair:
            return False        # pool exhausted
        if len(pair) < 2:
            continue            # 'RETRY': ghosts evicted, live peers may follow
        a, b = pair[0], pair[1]
        await set_partners(a, b)
        logger.info(f"Match formed: {a} <> {b}")
        await route(a, {"name": "PARTNER_FOUND", "data": "GO_FIRST"})
        await route(b, {"name": "PARTNER_FOUND", "data": "WAIT"})
    return True


async def _run_matcher_rounds_inmemory(max_rounds: int = 200) -> bool:
    """In-memory equivalent of run_matcher_rounds (single-instance only)."""
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        if len(_mem_waiting) < 2:
            return False
        # Oldest enqueue timestamp first (fairness mirrors Redis ZRANGE), bounded
        # to the same window the Lua matcher reads.
        waiting = sorted(_mem_waiting.items(), key=lambda x: x[1])[:MATCH_WINDOW]

        evicted = False
        candidate_a, _ = waiting[0]
        if not await is_connected(candidate_a):
            await remove_waiting(candidate_a)
            continue

        topics_a = _mem_topics.get(candidate_a, set())
        best_match = None
        first_alive = None

        for other, _ in waiting[1:]:
            if not await is_connected(other):
                await remove_waiting(other)
                evicted = True
                continue
            if first_alive is None:
                first_alive = other
            if not topics_a:
                break  # no topic preference -> longest-waiting peer is enough
            if topics_a & _mem_topics.get(other, set()):
                best_match = other
                break

        if best_match is None:
            best_match = first_alive
        if best_match is None:
            # Only ghosts besides candidate_a. If any were just evicted, live
            # peers may sit past the window -- mirrors the Lua 'RETRY' branch.
            if evicted:
                continue
            return False

        # Guard against a concurrent cleanup that ran during an await above
        if candidate_a not in _mem_waiting or best_match not in _mem_waiting:
            continue
        _mem_waiting.pop(candidate_a, None)
        _mem_waiting.pop(best_match, None)
        _mem_topics.pop(candidate_a, None)
        _mem_topics.pop(best_match, None)

        await set_partners(candidate_a, best_match)
        logger.info(f"Match formed: {candidate_a} <> {best_match}")
        await route(candidate_a, {"name": "PARTNER_FOUND", "data": "GO_FIRST"})
        await route(best_match, {"name": "PARTNER_FOUND", "data": "WAIT"})
    return True  # hit the round cap; work may remain


# --- Rate limiting --------------------------------------------------------

async def check_rate_limit(ip: str) -> bool:
    """Sliding-window limiter (per IP). Returns True if the connection is allowed.

    Fails open (allows the connection) when Redis is unavailable so an outage
    never locks every user out. In-memory mode also fails open.
    """
    if _inmemory_mode or not _redis:
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

    Doubles as this instance's Redis health signal, which is why nothing else
    polls for it. The connection here is long lived, and redis-py PINGs it every
    health_check_interval from inside get_message (parse_response -> check_health),
    so a socket that dropped raises straight away and one that went silently
    half-open raises within ~30s. Either way it lands in the except branch below,
    which is already responsible for reconnecting with backoff. Marking health
    from here therefore costs nothing: the PING is sent whether or not we react
    to it, and the hot path (relay, matching) gains no work at all.

    In in-memory mode (REDIS_URL not set), pub/sub is not needed
    since there is only one instance; this task sleeps indefinitely.
    """
    if _inmemory_mode:
        while True:
            await asyncio.sleep(3600)
    global _pubsub
    backoff = 0.5
    while True:
        if not _client:
            # No client at all: the URL could not be parsed, so retrying is futile.
            await asyncio.sleep(1.0)
            continue
        try:
            _pubsub = _client.pubsub(ignore_subscribe_messages=True)
            await _pubsub.psubscribe(CHAN_PATTERN)
            await _pubsub.subscribe(WAKEUP_CHANNEL)
            # Both subscribes are real commands, so reaching here proves the
            # connection works — including on the first pass after a failed
            # startup, which is how a cold start during an outage recovers.
            _set_redis_up(True)
            logger.info("Pub/Sub listener subscribed.")
            backoff = 0.5
            last_proof = time.monotonic()
            while True:
                msg = await _pubsub.get_message(timeout=5.0)
                if msg is None:
                    # A None here does NOT mean the link is healthy. redis-py does
                    # send a health-check PING from inside parse_response, but it
                    # reads the reply with this same non-blocking timeout, so a
                    # missing pong is indistinguishable from "no messages" and
                    # never raises. Measured: SIGSTOPing redis left the connection
                    # reported healthy indefinitely (still "redis" after 47s).
                    # So when the link has gone quiet, ask a question that has to
                    # be answered. A failure raises into the except below.
                    if time.monotonic() - last_proof >= HEALTH_PING_SECONDS:
                        # wait_for, not the client's socket_timeout: measured, a
                        # PING against a SIGSTOPed server was still blocked after
                        # 25s despite socket_timeout=5 and retry_on_timeout. An
                        # unbounded await here would wedge this whole task, which
                        # also carries cross-instance delivery.
                        await asyncio.wait_for(_client.ping(), HEALTH_PING_TIMEOUT)
                        last_proof = time.monotonic()
                    continue
                last_proof = time.monotonic()   # real traffic is its own proof
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
            # The connection is gone: stop admitting clients and stop issuing
            # commands until a resubscribe proves it is back.
            _set_redis_up(False)
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
