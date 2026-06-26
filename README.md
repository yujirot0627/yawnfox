# Yawnfox

Random video chat that pairs two strangers in the browser using WebRTC. Starlette handles signaling. Media flows peer to peer for low latency and low cost.

**Live demo:** <link if you have one>  
**Design document (PDF):** /docs/Yawnfox-SDD.pdf

---

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Running](#running)
- [Signaling protocol](#signaling-protocol)
- [Limits and known issues](#limits-and-known-issues)
- [Roadmap](#roadmap)
- [License](#license)

---

## Features

- One to one random pairing for audio and video
- Fast call setup using WebRTC with STUN for NAT discovery
- Minimal Starlette backend for HTTP and WebSocket signaling
- Simple browser UI written in JavaScript
- No database by default - ephemeral in memory state

---

## Architecture

```mermaid
flowchart LR
  A[Browser A] <--> |HTTP + WebSocket| S[Starlette Signaling]
  B[Browser B] <--> |HTTP + WebSocket| S
  A == SRTP over ICE ==> B
  subgraph NAT traversal
    STUN[(STUN servers)]
  end
  A --> STUN
  B --> STUN
```

### Scale-out architecture (Phase 1)

The backend is **stateless across instances**. All shared state lives in Redis,
so it can run as several Fly machines behind the Fly Proxy:

```
 Browser A ──ws──▶ Instance 1 ─┐                ┌─ Instance 2 ◀──ws── Browser B
                               ├──▶  Redis  ◀───┤
                               │  (Upstash)     │
   shared keys: waiting pool (ZSET), partner map, presence, rate-limit windows
   pub/sub:     yf:chan:<ws_id>  (cross-instance signaling relay)
                yf:wakeup        (matcher wakeup fan-out)
```

- **Matching** (`store.run_matcher_rounds`) runs on every instance but is
  serialized by a Redis lock (`yf:matcher:lock`), so it is not a single point of
  failure and never double-matches.
- **Signaling relay** delivers to a local socket when possible, otherwise
  publishes to the partner's `yf:chan:<ws_id>` channel; the instance that owns
  that socket forwards it. Two matched peers can therefore live on different
  machines.
- The only per-process state is the live WebSocket objects (which cannot be
  serialized). A Fly machine restart drops only that machine's sockets; the rest
  of the system keeps running, and TTLs self-heal any stale Redis entries.

---

## Tech stack

| Layer | Tech |
|-------|------|
| Frontend | SvelteKit 2 / Svelte 5, Tailwind CSS v4 (deployed on Vercel) |
| Backend | Python, Starlette + uvicorn (deployed on Fly.io) |
| Shared state | Redis (Upstash) via `redis-py`, async, over TLS |
| Realtime | WebRTC (P2P media), WebSocket signaling |

---

## Configuration

All backend configuration is via environment variables — see
[`backend/.env.example`](backend/.env.example) for the full list.

| Variable | Required | Description |
|----------|----------|-------------|
| `UPSTASH_REDIS_URL` | yes | Full `rediss://default:<password>@<host>:6379` URL from the Upstash console, **or** a bare host (combined with `UPSTASH_REDIS_TOKEN`). |
| `UPSTASH_REDIS_TOKEN` | no | Redis password, used only when `UPSTASH_REDIS_URL` is a bare host. |
| `REDIS_URL` | no | Local dev fallback (e.g. `redis://localhost:6379`), used only if `UPSTASH_REDIS_URL` is empty. |
| `CORS_ORIGIN` | recommended | Comma-separated allowed browser origins for the WebSocket + `/ping`. Empty = allow all (dev only). |
| `RATE_LIMIT_MAX` | no | Max new WS connections per IP per window (default `5`). |
| `RATE_LIMIT_WINDOW` | no | Sliding-window length in seconds (default `60`). |
| `CONN_TTL` / `PARTNER_TTL` / `TOPICS_TTL` | no | Redis key TTLs in seconds (defaults `90` / `300` / `1800`). |
| `PORT` | no | HTTP/WS port (default `8080`). |

> **Why `redis-py` over TLS and not the Upstash REST client?** Cross-instance
> signaling needs Redis **pub/sub** (`SUBSCRIBE`), which the REST API does not
> support. `redis-py` over the `rediss://` endpoint does. The Upstash console
> gives you this URL under the database's *Connect → redis-py* tab.

### Configure Upstash

1. Create a free database at <https://upstash.com> (Global / Regional both work).
2. Copy the **`rediss://…:6379`** connection URL (Connect → redis-py).

### Set Fly.io secrets

```bash
cd backend

# Redis (paste the full rediss:// URL — it already contains the password)
fly secrets set UPSTASH_REDIS_URL="rediss://default:YOUR_PASSWORD@your-db.upstash.io:6379"

# Lock the signaling WebSocket + /ping to your frontend origin
fly secrets set CORS_ORIGIN="https://yawnfox.com"

# (optional) tune the rate limiter
fly secrets set RATE_LIMIT_MAX=5 RATE_LIMIT_WINDOW=60
```

Secrets are encrypted and injected as env vars; setting them triggers a redeploy.

---

## Running

### Local (single process)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# point at a local redis (or set UPSTASH_REDIS_URL)
redis-server --daemonize yes
export REDIS_URL="redis://localhost:6379"

uvicorn main:app --reload --port 8080
```

Frontend:

```bash
cd frontend
npm install
npm run dev      # VITE_API_DOMAIN is read from frontend/.env
```

### Deploy (Fly.io)

```bash
cd backend
fly deploy
fly scale count 2     # run multiple instances (see Scaling below)
```

---

## Scaling

`fly.toml` keeps at least one machine warm (`min_machines_running = 1`) and
auto-starts more under load (concurrency-based). To run multiple instances:

```bash
fly scale count 2          # or more
fly scale count 2 --region otp,fra   # multi-region
```

No sticky-session config is required: an established WebSocket stays pinned to
its machine for the life of the connection, and all shared state is in Redis
(see the note in `fly.toml`).

---

## Testing

### Local multi-process matching test

This reproduces two backend instances sharing one Redis and verifies
cross-instance matching, SDP/ICE relay, and rate limiting.

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt          # includes redis + websockets

# 1. start redis
redis-server --port 6379 --daemonize yes --save "" --appendonly no

# 2. start two instances sharing that redis (separate terminals)
REDIS_URL=redis://localhost:6379 FLY_MACHINE_ID=inst-a uvicorn main:app --port 8001 --ws wsproto
REDIS_URL=redis://localhost:6379 FLY_MACHINE_ID=inst-b uvicorn main:app --port 8002 --ws wsproto

# 3. run the end-to-end test (connects a client to EACH instance)
python tests/test_multiprocess.py
```

Expected output: clients connected to different instances get paired, exchange
SDP/ICE through Redis pub/sub, and the 6th+ connection from one IP is rejected
with `RATE_LIMITED`.

### Rate limit (manual)

With `RATE_LIMIT_MAX=5 / RATE_LIMIT_WINDOW=60`, open 6 WebSocket connections to
`/api/matchmaking` from the same IP within a minute. The first five connect; the
sixth receives `{"name":"RATE_LIMITED", ...}` and is closed with code `1013`.

### Redis-down behaviour

- **Down at startup:** the server still boots; `/ping` reports `"redis": false`
  and clients receive `SERVER_UNAVAILABLE` instead of hanging.
- **Down mid-operation:** Redis errors are caught and logged; the process never
  crashes, and it auto-reconnects (including pub/sub re-subscription) when Redis
  returns.

---

## Signaling protocol

JSON messages over the `/api/matchmaking` WebSocket:

| Direction | `name` | Notes |
|-----------|--------|-------|
| client → server | `PAIRING_START` | optional `topics: string[]` (max 3) |
| client → server | `PAIRING_ABORT` / `LEAVE` | leave the queue / current partner |
| client → server | `CHAT` | `data: string`, relayed to partner |
| client ↔ server | `SDP_OFFER` / `SDP_ANSWER` / `SDP_ICE_CANDIDATE` | relayed verbatim to partner |
| server → client | `PARTNER_FOUND` | `data: "GO_FIRST" \| "WAIT"` |
| server → client | `PARTNER_LEFT` | partner disconnected |
| server → client | `RATE_LIMITED` / `SERVER_UNAVAILABLE` | connection refused / degraded |
