"""Deterministic tests for the matcher selection logic and its Redis cost.

Drives store.run_matcher_rounds() in-process against a bare Redis, seeding the
waiting pool by hand. No backend instance is started, so nothing races the
matcher and every case is reproducible.

    redis-server --port 6390 --daemonize yes --save "" --appendonly no
    REDIS_URL=redis://localhost:6390 python tests/test_matcher.py

Covers what test_multiprocess.py structurally cannot: it gives both clients the
same topic, so it passes whether topic preference works or not.

Env overrides: REDIS_URL (default redis://localhost:6390).
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("REDIS_URL", "redis://localhost:6390")

import redis.asyncio as aioredis

import store  # noqa: E402  (must follow the REDIS_URL default: see store._inmemory_mode)

REDIS_URL = os.environ["REDIS_URL"]

passed = []
failed = []


def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' -> ' + detail) if detail else ''}")


async def reset(r):
    """Drop every yf: key so each case starts from a known pool."""
    keys = [k async for k in r.scan_iter(match=f"{store.PREFIX}:*", count=1000)]
    for i in range(0, len(keys), 500):
        await r.delete(*keys[i:i + 500])


async def seed(r, ws_id, score, topics=(), live=True):
    """Put one member in the waiting pool at an explicit score (= queue order)."""
    await r.zadd(store.WAITING_KEY, {ws_id: score})
    if topics:
        await r.sadd(store.topics_key(ws_id), *topics)
    if live:
        await r.set(store.conn_key(ws_id), "test-instance")


async def test_topic_preference(r):
    print("\nTest 1: topic preference beats queue order")
    await reset(r)
    await seed(r, "a", 1, ["chess"])
    await seed(r, "b", 2, ["cooking"])
    await seed(r, "c", 3, ["chess"])

    await store.run_matcher_rounds(max_rounds=1)

    check("oldest waiter pairs with the topic match, not the next in line",
          await store.get_partner("a") == "c", f"a -> {await store.get_partner('a')}")
    check("the non-matching client stays in the pool",
          await r.zrange(store.WAITING_KEY, 0, -1) == ["b"])
    check("topics of the paired clients are cleaned up",
          not await r.exists(store.topics_key("a"), store.topics_key("c")))


async def test_no_topic_fallback(r):
    print("\nTest 2: with no topics, the two oldest pair")
    await reset(r)
    await seed(r, "a", 1)
    await seed(r, "b", 2)
    await seed(r, "c", 3)

    await store.run_matcher_rounds(max_rounds=1)

    check("a pairs with b (queue order preserved)", await store.get_partner("a") == "b")
    check("c is left waiting", await r.zrange(store.WAITING_KEY, 0, -1) == ["c"])


async def test_ghosts_past_the_window(r):
    print("\nTest 3: live clients behind a ghost block larger than the window")
    await reset(r)
    # 70 > MATCH_WINDOW, so round 1 sees nothing but ghosts and cannot pair.
    for i in range(70):
        await seed(r, f"ghost-{i:03d}", i, live=False)
    await seed(r, "a", 900)
    await seed(r, "b", 901)

    more = await store.run_matcher_rounds(max_rounds=5)

    check("the live pair still matches", await store.get_partner("a") == "b",
          f"a -> {await store.get_partner('a')}")
    check("every ghost was evicted", await r.zcard(store.WAITING_KEY) == 0,
          f"zcard={await r.zcard(store.WAITING_KEY)}")
    check("reports the pool exhausted once drained", more is False)


async def test_cost_is_not_proportional_to_pool(r):
    print("\nTest 4: cost does not scale with pool depth (the O(N) fix)")
    await reset(r)
    pipe = r.pipeline(transaction=False)
    for i in range(5000):
        pipe.zadd(store.WAITING_KEY, {f"ghost-{i:04d}": i})
    await pipe.execute()
    await seed(r, "a", 90000)
    await seed(r, "b", 90001)

    await r.config_resetstat()
    await store.run_matcher_rounds(max_rounds=200)
    info = await r.info("commandstats")

    def calls(cmd):
        return info.get(f"cmdstat_{cmd}", {}).get("calls", 0)

    # EVAL is client-issued (and the unit Upstash bills); EXISTS/ZREM/SMEMBERS
    # below it run inside the script. The old matcher issued one EXISTS per
    # candidate as its own round-trip, so this pool cost 5000+ of them.
    evals = calls("eval") + calls("evalsha")
    check("clearing 5000 ghosts + 1 pairing costs < 100 client round-trips",
          evals < 100, f"eval={evals}, internal exists={calls('exists')}")
    check("the pair was still formed", await store.get_partner("a") == "b")


async def test_inmemory_parity(r):
    print("\nTest 5: in-memory mode makes the same choice")
    await reset(r)
    store._inmemory_mode = True
    try:
        store._mem_waiting.update({"a": 1, "b": 2, "c": 3})
        store._mem_topics.update({"a": {"chess"}, "b": {"cooking"}, "c": {"chess"}})
        store._mem_connections.update({"a", "b", "c"})

        await store.run_matcher_rounds(max_rounds=1)

        check("in-memory matcher also prefers the topic match",
              store._mem_partners.get("a") == "c", f"a -> {store._mem_partners.get('a')}")
        check("in-memory matcher leaves the non-match queued",
              list(store._mem_waiting) == ["b"])
    finally:
        store._inmemory_mode = False
        for d in (store._mem_waiting, store._mem_topics, store._mem_partners):
            d.clear()
        store._mem_connections.clear()


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    await store.connect()
    try:
        await test_topic_preference(r)
        await test_no_topic_fallback(r)
        await test_ghosts_past_the_window(r)
        await test_cost_is_not_proportional_to_pool(r)
        await test_inmemory_parity(r)
        await reset(r)
    finally:
        await store.close()
        await r.aclose()

    print(f"\n==== {len(passed)} passed, {len(failed)} failed ====")
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
