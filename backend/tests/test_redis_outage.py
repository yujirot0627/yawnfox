"""Redis outage and recovery behaviour.

Self-contained: starts its own redis-server and backend instances on dedicated
ports, then kills Redis mid-run. The other suites assume a Redis that stays up,
so none of them can reach this path.

    python tests/test_redis_outage.py

Env overrides: REDIS_PORT (6391), INST_PORT (8003), COLD_PORT (8004).
"""
import os
import sys
import json
import signal
import asyncio
import subprocess
import urllib.error
import urllib.request

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYBIN = os.path.join(BACKEND, "venv", "bin", "uvicorn")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6391"))
INST_PORT = int(os.environ.get("INST_PORT", "8003"))
COLD_PORT = int(os.environ.get("COLD_PORT", "8004"))
HUNG_PORT = int(os.environ.get("HUNG_PORT", "8009"))

passed = []
failed = []
procs = []


def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' -> ' + detail) if detail else ''}")


# --- process helpers ------------------------------------------------------

def redis_up():
    subprocess.run(
        ["redis-server", "--port", str(REDIS_PORT), "--daemonize", "yes",
         "--save", "", "--appendonly", "no"],
        check=True, capture_output=True,
    )


def redis_down():
    subprocess.run(["redis-cli", "-p", str(REDIS_PORT), "shutdown", "nosave"],
                   capture_output=True)


def redis_pid():
    out = subprocess.run(["redis-cli", "-p", str(REDIS_PORT), "info", "server"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("process_id:"):
            return int(line.split(":")[1].strip())
    return None


def start_instance(port, name, **extra_env):
    env = {
        **os.environ,
        "REDIS_URL": f"redis://localhost:{REDIS_PORT}",
        "FLY_MACHINE_ID": name,
        "RATE_LIMIT_MAX": "1000",   # this suite opens more than the default 5
        **extra_env,
    }
    p = subprocess.Popen(
        [PYBIN, "main:app", "--port", str(port), "--ws", "wsproto"],
        cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    procs.append(p)
    return p


def ping(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=3) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


async def wait_ping(port, want_mode, want_ready, timeout=30.0):
    """Poll /ping until it reports the wanted state. Returns seconds taken, or None."""
    loop = asyncio.get_event_loop()
    start = loop.time()
    while loop.time() - start < timeout:
        p = await asyncio.to_thread(ping, port)
        if p and p.get("mode") == want_mode and p.get("ready") is want_ready:
            return loop.time() - start
        await asyncio.sleep(0.2)
    return None


def ws_url(port):
    return f"ws://127.0.0.1:{port}/api/matchmaking"


async def recv_until(ws, name, timeout=6.0):
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - loop.time()))
        if msg.get("name") == name:
            return msg
    raise asyncio.TimeoutError(name)


# --- tests ----------------------------------------------------------------

async def main():
    redis_down()          # clear anything left by an earlier run
    await asyncio.sleep(0.3)
    redis_up()
    start_instance(INST_PORT, "inst-outage")
    if not await wait_ping(INST_PORT, "redis", True, timeout=30):
        print("instance never came up; aborting")
        sys.exit(1)

    print("\nTest 1: healthy baseline")
    p = await asyncio.to_thread(ping, INST_PORT)
    check("reports mode=redis, ready=true", p["mode"] == "redis" and p["ready"] is True, str(p))

    # Pair two clients BEFORE the outage; they stay open for test 4.
    a = await connect(ws_url(INST_PORT))
    b = await connect(ws_url(INST_PORT))
    await a.send(json.dumps({"name": "PAIRING_START", "topics": []}))
    await b.send(json.dumps({"name": "PAIRING_START", "topics": []}))
    await recv_until(a, "PARTNER_FOUND")
    await recv_until(b, "PARTNER_FOUND")
    check("clients are admitted and matched while healthy", True)

    print("\nTest 2: the outage is detected")
    redis_down()
    took = await wait_ping(INST_PORT, "redis-down", False, timeout=45)
    check("mode flips to redis-down and ready to false", took is not None,
          f"after {took:.1f}s" if took else "never flipped")

    print("\nTest 3: new clients are told, not left hanging")
    told = False
    try:
        async with connect(ws_url(INST_PORT)) as c:
            msg = json.loads(await asyncio.wait_for(c.recv(), timeout=5))
            told = msg.get("name") == "SERVER_UNAVAILABLE"
    except (ConnectionClosed, asyncio.TimeoutError, OSError):
        pass
    check("a new connection receives SERVER_UNAVAILABLE", told)

    print("\nTest 4: existing sessions are not torn down")
    # Media and chat are peer-to-peer, so an established call never touches the
    # server. What matters here is that losing Redis does not disconnect anyone.
    still_open = True
    for sock in (a, b):
        try:
            await asyncio.wait_for(sock.recv(), timeout=2)
            still_open = False      # any frame here would be a PARTNER_LEFT/close
        except asyncio.TimeoutError:
            pass                    # silent and open, as expected
        except ConnectionClosed:
            still_open = False
    check("an already-matched pair stays connected through the outage", still_open)

    print("\nTest 5: an instance that starts DURING the outage still recovers")
    start_instance(COLD_PORT, "inst-cold")
    cold = await wait_ping(COLD_PORT, "redis-down", False, timeout=30)
    check("cold start with no Redis reports redis-down", cold is not None,
          f"after {cold:.1f}s" if cold else "never reported")

    print("\nTest 6: recovery, with no restart")
    redis_up()
    back = await wait_ping(INST_PORT, "redis", True, timeout=45)
    check("the running instance returns to mode=redis, ready=true", back is not None,
          f"after {back:.1f}s" if back else "never recovered")
    cold_back = await wait_ping(COLD_PORT, "redis", True, timeout=45)
    check("the cold-started instance comes up on its own", cold_back is not None,
          f"after {cold_back:.1f}s" if cold_back else "never recovered")

    matched = False
    try:
        async with connect(ws_url(INST_PORT)) as c, connect(ws_url(INST_PORT)) as d:
            await c.send(json.dumps({"name": "PAIRING_START", "topics": []}))
            await d.send(json.dumps({"name": "PAIRING_START", "topics": []}))
            await recv_until(c, "PARTNER_FOUND")
            await recv_until(d, "PARTNER_FOUND")
            matched = True
    except Exception as e:
        print(f"    (matching after recovery raised: {e})")
    check("matching works again after recovery", matched)

    for sock in (a, b):
        try:
            await sock.close()
        except Exception:
            pass

    print("\nTest 7: a HUNG Redis is detected, not just a dropped socket")
    # The hard case. A server that keeps the socket open but stops answering
    # raises nothing: get_message just keeps returning None, and redis-py's own
    # health-check PING is read with that same non-blocking timeout, so a missing
    # pong is invisible. Only the explicit probe finds this. HEALTH_PING_SECONDS
    # is turned down so the test does not have to wait out the 120s default.
    start_instance(HUNG_PORT, "inst-hung", HEALTH_PING_SECONDS="5")
    if await wait_ping(HUNG_PORT, "redis", True, timeout=30):
        pid = redis_pid()
        os.kill(pid, signal.SIGSTOP)            # alive, connected, unresponsive
        try:
            hung = await wait_ping(HUNG_PORT, "redis-down", False, timeout=40)
            check("a hung server is detected", hung is not None,
                  f"after {hung:.1f}s" if hung else "never detected")
        finally:
            os.kill(pid, signal.SIGCONT)
        rec = await wait_ping(HUNG_PORT, "redis", True, timeout=40)
        check("and recovers once it answers again", rec is not None,
              f"after {rec:.1f}s" if rec else "never recovered")
    else:
        check("a hung server is detected", False, "instance never came up")


def cleanup():
    for p in procs:
        try:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    redis_down()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        cleanup()
    print(f"\n==== {len(passed)} passed, {len(failed)} failed ====")
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(1)
