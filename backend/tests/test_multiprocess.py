"""
End-to-end test for the Redis-backed Yawnfox backend.

Run two backend instances that share one Redis, then:

    redis-server --port 6379 --daemonize yes --save "" --appendonly no
    REDIS_URL=redis://localhost:6379 FLY_MACHINE_ID=inst-a uvicorn main:app --port 8001 --ws wsproto
    REDIS_URL=redis://localhost:6379 FLY_MACHINE_ID=inst-b uvicorn main:app --port 8002 --ws wsproto
    python tests/test_multiprocess.py

Verifies:
  1. Cross-instance matching (clients on different instances get paired)
  2. Cross-instance signaling relay (SDP/ICE/PARTNER_LEFT across instances)
  3. Same-instance matching (fast local path)
  4. Sliding-window rate limiting

Env overrides: INST_A_URL, INST_B_URL, REDIS_URL.
"""
import os
import sys
import json
import asyncio

import redis.asyncio as aioredis
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

URL_A = os.environ.get("INST_A_URL", "ws://127.0.0.1:8001/api/matchmaking")
URL_B = os.environ.get("INST_B_URL", "ws://127.0.0.1:8002/api/matchmaking")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

passed = []
failed = []


def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' -> ' + detail) if detail else ''}")


async def recv(ws, timeout=6.0):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


async def recv_until(ws, name, timeout=6.0):
    """Read frames until one with the given name arrives (skips others)."""
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        msg = await recv(ws, timeout=end - loop.time())
        if msg.get("name") == name:
            return msg
    raise asyncio.TimeoutError(f"did not receive {name}")


async def test_cross_instance_match_and_relay():
    print("\nTest 1: cross-instance matching + SDP/ICE relay")
    async with connect(URL_A) as a, connect(URL_B) as b:
        await a.send(json.dumps({"name": "PAIRING_START", "topics": ["coding"]}))
        await b.send(json.dumps({"name": "PAIRING_START", "topics": ["coding"]}))

        msg_a = await recv_until(a, "PARTNER_FOUND")
        msg_b = await recv_until(b, "PARTNER_FOUND")
        check("A on instance A receives PARTNER_FOUND", msg_a.get("name") == "PARTNER_FOUND", msg_a.get("data"))
        check("B on instance B receives PARTNER_FOUND", msg_b.get("name") == "PARTNER_FOUND", msg_b.get("data"))
        check("exactly one GO_FIRST and one WAIT",
              {msg_a.get("data"), msg_b.get("data")} == {"GO_FIRST", "WAIT"})

        offerer, answerer = (a, b) if msg_a.get("data") == "GO_FIRST" else (b, a)

        await offerer.send(json.dumps({"name": "SDP_OFFER", "data": "OFFER_SDP_BLOB"}))
        got = await recv_until(answerer, "SDP_OFFER")
        check("SDP_OFFER relayed to partner on the other instance", got.get("data") == "OFFER_SDP_BLOB")

        await answerer.send(json.dumps({"name": "SDP_ANSWER", "data": "ANSWER_SDP_BLOB"}))
        got = await recv_until(offerer, "SDP_ANSWER")
        check("SDP_ANSWER relayed back across instances", got.get("data") == "ANSWER_SDP_BLOB")

        await offerer.send(json.dumps({"name": "SDP_ICE_CANDIDATE", "data": "ICE_BLOB"}))
        got = await recv_until(answerer, "SDP_ICE_CANDIDATE")
        check("ICE candidate relayed across instances", got.get("data") == "ICE_BLOB")

        await offerer.close()
        got = await recv_until(answerer, "PARTNER_LEFT")
        check("PARTNER_LEFT delivered when partner disconnects", got.get("name") == "PARTNER_LEFT")


async def test_same_instance_match():
    print("\nTest 2: same-instance matching still works (fast local path)")
    async with connect(URL_A) as a, connect(URL_A) as b:
        await a.send(json.dumps({"name": "PAIRING_START", "topics": []}))
        await b.send(json.dumps({"name": "PAIRING_START", "topics": []}))
        msg_a = await recv_until(a, "PARTNER_FOUND")
        msg_b = await recv_until(b, "PARTNER_FOUND")
        check("both clients on instance A matched (random fallback)",
              msg_a.get("name") == "PARTNER_FOUND" and msg_b.get("name") == "PARTNER_FOUND")


async def flush_rate_keys():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    keys = [k async for k in r.scan_iter(match="yf:rl:*")]
    if keys:
        await r.delete(*keys)
    await r.aclose()


async def test_rate_limit():
    print("\nTest 3: rate limiting (default RATE_LIMIT_MAX=5 / 60s per IP)")
    await flush_rate_keys()  # isolate from connections opened by tests 1 and 2
    accepted, limited = 0, 0
    for _ in range(7):
        try:
            ws = await connect(URL_A)
        except Exception:
            limited += 1
            continue
        try:
            msg = await recv(ws, timeout=1.5)
            if msg.get("name") == "RATE_LIMITED":
                limited += 1
            else:
                accepted += 1
        except asyncio.TimeoutError:
            accepted += 1            # idle accepted connection (no frame sent)
        except ConnectionClosed:
            limited += 1             # server closed us before we read a frame
        finally:
            try:
                await ws.close()
            except Exception:
                pass
    check("first 5 connections accepted", accepted == 5, f"accepted={accepted}")
    check("connections beyond the limit rejected", limited == 2, f"limited={limited}")


async def main():
    await test_cross_instance_match_and_relay()
    await test_same_instance_match()
    await test_rate_limit()
    print(f"\n==== {len(passed)} passed, {len(failed)} failed ====")
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
