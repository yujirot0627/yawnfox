# Yawnfox — Code Quality Audit

> **Date:** 2026-08-11
> **Scope:** `frontend/` (SvelteKit) + `backend/` (Python / Starlette)
> **Lens:** maintainability and correctness at ~5,000 concurrent users — not runtime performance
> **Codebase size:** 5,010 lines of source (backend 1,263 · backend tests 599 · frontend ~3,148)
>
> Quick wins 1–20 from §3 **have been applied** and a CI workflow added. See
> [§5 Applied Changes](#5-applied-changes-2026-08-11) for exactly what changed and the
> verification results. Everything in §2 describes the state **before** those fixes;
> each item is tagged ✅ **applied** or ⬜ **still open**.
>
> **A follow-up investigation then found a connection leak with privacy consequences —
> the most serious defect in this document.** It was confirmed by measurement and fixed.
> See [§7](#7-follow-up-connection-leak-in-peerjs-2026-08-11). If you read only one
> section, read that one.
>
> Companion documents: [`yawnfox-codebase-report.md`](yawnfox-codebase-report.md) (2026-06-26)
> and [`yawnfox-status-report.md`](yawnfox-status-report.md) (2026-08-10).
>
> **Commits:** `d6a615e` (quick wins + CI) · `4181d3c` (leak fix + test harness)

---

## 1. Overall Assessment

**Good, and materially better than the June review.** The backend is the strongest part of the
codebase: `store.py` and `main.py` are dense but genuinely well-reasoned, and — unusually —
the comments explain *why* a decision was made and what it cost, with measured numbers.
Every non-obvious constant (`MATCH_WINDOW`, `MATCHER_LOCK_MS`, `HEALTH_PING_SECONDS`,
`PAIRING_COST`) carries its own justification. That is the single biggest asset for onboarding
here, and it should be protected.

The weakness was asymmetric: **the backend was tested and linted-clean; the frontend was
neither.** `npm run lint` was red (14 eslint errors, 7 prettier failures), there was no CI to
notice, no type checking (`checkJs: false`, no `svelte-check`), and the two largest files —
`Game.svelte` (868 lines) and `chat/+page.svelte` (630) — have grown past the point where one
person can hold them in their head.

Three cross-cutting themes:

- **Verification was manual.** 35 backend checks + 2 JS self-checks all exist and all pass,
  but every one required a human to start Redis and type a command. Nothing ran on commit.
  *(Addressed — see §5.)*
- **Documentation had drifted behind the last three months of work.** The root README still
  described the pre-Phase-2 protocol; `frontend/README.md` was a truncated stale copy of it.
  *(Addressed — see §5.)*
- **Consistency is good within each subsystem and poor between them.** Two mini-games, two
  sync models, two validation standards; one Svelte 5 file among nine legacy-syntax files.
  *(Still open — these are refactors, not quick wins.)*

At ~5,000 concurrent users the code is architecturally fine — the Redis migration did its job —
with one throughput ceiling worth knowing about (§2.5).

---

## 2. Findings by Area

### 2.1 Lint / formatting / dead code

**Tooling status at audit time**

| Tool | Configured in repo? | Result |
| --- | --- | --- |
| eslint | yes (`eslint.config.js`) | **14 errors** |
| prettier | yes (`.prettierrc`) | **7 files fail `--check`** |
| ruff / flake8 / black | **no Python linter configured at all** | ruff default ruleset: 15 findings, all benign |
| svelte-check | not installed | — |

`npm run lint` (= `prettier --check . && eslint .`) **failed.** Nothing caught it.

---

**HIGH — `npm run lint` is red and nothing enforces it** ✅ **applied**
Every finding below was pre-existing and unnoticed because there was no CI and the script was
never run in an automated context.

**MEDIUM — eslint: 14 errors** ✅ **applied**

| File:line | Error |
| --- | --- |
| `frontend/src/lib/peer.js:252,259,267,284` | `'_' is defined but never used` + **empty block statement** ×4 — the `catch (_) {}` blocks in `disconnect()` |
| `frontend/src/routes/+page.svelte:2` | `onMount` imported, never used |
| `frontend/src/routes/chat/+page.svelte:2` | `tick` imported, never used |
| `frontend/src/routes/chat/+page.svelte:329` | **unkeyed `{#each topics as t}`** |
| `frontend/src/routes/chat/+page.svelte:440` | **unkeyed `{#each topics as t, i}`** |
| `frontend/src/routes/+page.svelte:187` | stale `svelte-ignore` — `a11y_no_static_element_interactions` written **twice** (lines 187 and 188) |
| `frontend/src/routes/chat/+page.svelte:391` | stale `svelte-ignore a11y_media_has_caption` — attached to the wrapping `<div>`, not the `<video>`; the video is `muted` so the rule never fires |

The four empty catches in `peer.js` were the notable ones: `disconnect()` swallowed every
failure from `LEAVE`-send, datachannel close, peer close, and websocket close with no logging.
If a teardown path ever broke, it was invisible.

The unkeyed `#each` at line 440 is the one with real behaviour attached — it renders topic
chips with an index-based `removeTopic(i)` button. Unkeyed + index-based removal is exactly
the pattern where Svelte's DOM reuse mis-associates rows.

**MEDIUM — Python has no linter or formatter configured** ✅ **applied**
`ruff --isolated --select E4,E7,E9,F` returned **15 findings, all `E402`** in `main.py:12–28` —
and all of them are the deliberate, well-documented `load_dotenv()`-before-`import store`
ordering. **Zero unused imports, zero undefined names, zero dead Python.** That is a clean
result — but it was clean by accident, not by policy.

**LOW — 33 blind `except Exception`, 10 of them `except: pass`** ✅ **partially applied**
Most are correct best-effort teardown and are commented as such. The two that hid a *live*
failure rather than a teardown one were fixed:

- `main.py:275` and `main.py:289` — swallowed the failure to send `RATE_LIMITED` /
  `SERVER_UNAVAILABLE`. If those sends failed, the client was closed with no explanation and
  no log line.

The remaining ~31 are genuine teardown paths and were left alone.

**LOW — dead files and assets** ✅ **applied**

| Item | Status |
| --- | --- |
| `frontend/src/lib/index.js` | **0 bytes** — empty file, imported by nothing |
| `frontend/static/spinner.svg` | unreferenced anywhere in `src/` |
| `frontend/static/favicon copy.ico` | unreferenced; the name is literally a Finder duplicate |
| `.DS_Store`, `backend/.DS_Store` | **tracked in git** |
| `frontend/package.json` | shipped `adapter-auto`, `adapter-netlify`, `adapter-node`, `adapter-static` — only `adapter-vercel` is used |
| `/.dockerignore` (repo root) | only ignores `node_modules`; the Dockerfile lives in `backend/` and uses `backend/.dockerignore`. Root file is vestigial — ⬜ **left in place** (harmless, and removing it risks a Vercel-side assumption) |

**LOW — dead code path: `ensureServerAwake` (`peer.js:468–484`)** ✅ **applied**
Flagged in the June review, flagged again in the August status report, still open until now.
It tested `data?.message?.includes('waking up')`; `/ping` returns `"Server is awake"`
(`main.py:426`). The branch — including the `alert()` and the 30-second sleep — could never
execute. Doubly dead since `min_machines_running = 1`. Because the only writer of the
`lastServerWake` throttle lived *inside* that dead branch, the throttle was dead too, which
reduced the whole function to "fetch `/ping`, discard the result". Removed entirely.

**LOW — debug hook shipped to production** ✅ **applied**
`chat/+page.svelte:168` — `window.setAppState = setState;` exposed the internal state machine
on `window` for anyone to drive.

---

### 2.2 Consistency

**HIGH — the two mini-games use different sync models *and* different input-validation standards** ⬜ **still open**

Within one 868-line component:

| | Nose Hockey | Tic-tac-toe |
| --- | --- | --- |
| **Authority** | Host-authoritative — host runs `step()`, ships ball state at 30 Hz; guest extrapolates and snaps | **Replicated** — no authority; both peers apply the same validated move |
| **Divergence handling** | Guest overwritten by host each tick | Relies on `canPlay()` being byte-identical on both sides |
| **Layout** | `dispatch('active', true)` → forces 50/50 | never dispatches `active` → no layout change |

Both models are individually sound and both are argued for in comments. The cost is that a
reader must hold two mental models at once, and a change to the invite/countdown/result flow —
which they **share** — has to be reasoned about twice.

The validation gap is the sharper edge. Wire messages are policed to three different standards:

```js
game_move    → re-validated via canPlay()           ✅ strict
game_state   → every field Number.isFinite-checked  ✅ strict
game_paddle  → clampPaddle()                        ✅ strict
game_invite  → kind = m.kind ?? 'hockey'            ❌ unvalidated
game_start   → kind = m.kind ?? kind                ❌ unvalidated
```

A peer sending `{type:'game_invite', kind:'anything'}` sets `kind` to an arbitrary string.
Effect is contained (`kind !== 'hockey'` skips the canvas; the template's `{:else}` renders the
TTT board, but `playCell` guards `kind !== 'ttt'` and returns) — so the result is a dead,
unclickable board rather than a crash. **Not a security hole.** But it is the one message field
in the whole protocol that isn't checked, sitting next to three that are.

**MEDIUM — one Svelte 5 runes file among nine legacy-syntax files** ⬜ **still open**

Svelte 5.26.2 is installed. Usage:

| File | Syntax |
| --- | --- |
| `routes/+layout.svelte` | **runes** — `$props()` |
| `lib/Game.svelte` | legacy — 4 `export let`, 7 `$:`, `createEventDispatcher`, 4 `on:` |
| `lib/TicTacToeBoard.svelte` | legacy — 4 `export let`, `createEventDispatcher`, 1 `on:` |
| `routes/chat/+page.svelte` | legacy — **16** `on:` directives |
| `routes/+page.svelte` | legacy — 6 `on:` |

`createEventDispatcher` and `on:` event directives are both deprecated in Svelte 5. This works
today, but it means new contributors see two dialects and have to guess which is current — and
the answer ("the one used in the smallest file") is not discoverable. *A note was added to
`frontend/README.md` telling contributors to match the file they are editing; picking one
dialect remains a tracked refactor.*

**MEDIUM — error surfacing is inconsistent across three mechanisms** ⬜ **partially open**
The app has a well-built notice system: `Game.svelte:showNotice()` renders a styled toast
*outside* the chat overlay specifically so the Messages toggle can't hide it (the comment says
so explicitly). And `addMessage(..., 'system')` for chat-level events. Yet `peer.js` reached
for **`alert()`** twice:

- `peer.js:84` — `RATE_LIMITED` / `SERVER_UNAVAILABLE` — ⬜ **still open**
- `peer.js:478` — the dead wake-up branch — ✅ **removed with the function**

One `alert()` remains. Routing it through the existing notice UI is a small change but it
crosses a component boundary (`peer.js` → chat page callback), so it is listed as a refactor
rather than a quick win.

**LOW — `nose.js` / `trackFace` naming mismatch** ⬜ **still open**
Within one 108-line file: the module is `nose.js`, exports `loadNose()` and `trackFace()`, and
its own header comment says *"The paddle follows the centre of the face bounding box… no
landmark network."* Consumers compound it: `startNoseTracking()`, `stopNoseTracking()`,
`onNose(pos)`, `nose = pos`, `noseWarning`. Nothing in the implementation touches a nose.
"Nose Hockey" is the product name and should stay; the module is tracking a face. A rename
touches ~15 call sites across two files — mechanical, but not a one-liner.

**LOW — frontend API base URL configured two different ways** ✅ **applied**

```js
peer.js:49   const ws = new WebSocket(`${protocol}://${import.meta.env.VITE_API_DOMAIN}/api/matchmaking`);
peer.js:473  const res = await fetch('https://api.yawnfox.com/ping', ...);
```

The WebSocket honoured `VITE_API_DOMAIN`; the ping was hardcoded to production, so a local dev
run pointed at a local backend still pinged prod. Line 50 also carried a commented-out
`ws://localhost:8000` alternative — a third configuration mechanism. Removing
`ensureServerAwake` eliminated the hardcoded URL; the commented-out line was deleted too.
`VITE_API_DOMAIN` is now the single mechanism, documented in `frontend/.env.example`.

---

### 2.3 Test Coverage

**Is there CI?** There was none — no `.github/` directory, no CI config of any kind.
✅ **A workflow has been added; see §5.**

**What exists and is genuinely good:**

| Suite | Checks | Covers |
| --- | --- | --- |
| `backend/tests/test_matcher.py` | 12 | topic preference beats queue order, no-topic fallback, ghosts past `MATCH_WINDOW`, **O(1) cost at 5,000 waiting**, in-memory/Redis parity |
| `backend/tests/test_multiprocess.py` | 12 | cross-instance matching, SDP/ICE/`PARTNER_LEFT` relay via pub/sub, same-instance fast path, connection rate limit, per-socket token bucket |
| `backend/tests/test_redis_outage.py` | 11 | outage detection, `SERVER_UNAVAILABLE`, established pairs survive, cold start during outage, self-recovery, **`SIGSTOP`-hung Redis** |
| `frontend/src/lib/pong.js` | ~25 asserts | walls, saves, spin, serve direction, substep tunnelling, NaN, 3,000-frame stuck-in-paddle sweep |
| `frontend/src/lib/tictactoe.js` | ~30 asserts | all 8 lines × 2 marks, draws, turn order, every `canPlay` guard, replay determinism |

**35 backend checks confirmed** — the status report's number is accurate. The outage suite in
particular (killing a real Redis, then `SIGSTOP`-ing one to simulate a hang) is better than
most production codebases have.

**HIGH — the entire frontend interaction layer is untested, and it is where the risk now lives** ⬜ **still open**

Untested, ranked by how much would break silently:

1. **`peer.js` (now 461 lines) — the WebRTC state machine.** Zero coverage. Offer/answer/ICE
   ordering, the `_pendingCandidates` queue, `_remoteDescSet` gating, the 15-second connect
   timeout, the `PARTNER_LEFT`-while-not-CONNECTED → re-queue path, `closedByLocal`
   suppression on datachannel close. This is the most intricate logic in the repo and the most
   likely to regress. Its own header comment offers `options.connectTimeoutMs` "used by the
   self-check" — **there is no self-check.**
   > ⚠️ **This prediction landed.** A follow-up investigation found four real defects in
   > exactly this file, including one with privacy consequences — see [§7](#7-follow-up-connection-leak-in-peerjs-2026-08-11).
   > `tests/leak.spec.js` now covers the connection *lifecycle*; the handshake logic listed
   > above is still untested.
2. **Camera/MediaStream lifecycle.** The August fix (one stream per session, released only in
   `onDestroy`) is guarded by five separate comments warning future readers not to call
   `stop()` in `disconnect()`. Comments are the only enforcement; a regression here
   re-introduces the exact bug that was just fixed and shows up as a stuck camera light.
3. **`Game.svelte` protocol handling.** `pong.js` and `tictactoe.js` are well covered, but the
   invite → accept → countdown → play → over state machine that drives them — including the
   both-invited-at-once tie-break via `peer.isOfferer`, the busy-decline, and the
   camera-cancel — is not.
4. **`chat/+page.svelte` peer recreation.** `setState('DISCONNECTED_REMOTE')` calls
   `createPeer()` without awaiting; `handleConnectFailed()` and `leavePairing()` call it on
   other paths. No test asserts exactly one live peer/socket after N transitions.

**MEDIUM — two of the three backend suites are not CI-runnable as written** ⬜ **still open**

- `test_redis_outage.py:24` hardcodes `PYBIN = backend/venv/bin/uvicorn`. Fails on any machine
  without a venv at that exact path.
- `test_multiprocess.py` requires two uvicorn instances started by hand in separate terminals
  first.
- None use pytest conventions (they're `__main__` scripts with a hand-rolled `check()`), so
  `pytest backend/tests/` collects nothing useful.
- Neither `pytest` nor a redis server is declared as a test dependency.

`test_matcher.py` **is** CI-runnable (it only needs a bare Redis and drives `store` in-process)
and is what the new workflow runs. The other two are documented in the workflow as
deliberately excluded, with the reason.

**LOW — `test_multiprocess.py:191` catches bare `Exception` around the recovery assertion and
prints instead of failing.** ⬜ **still open.** A real error there reads as a soft
"raised: ..." note rather than a red test.

---

### 2.4 Documentation Drift

**MEDIUM — root `README.md` described the pre-Phase-2 protocol** ✅ **applied**

| Line | Claim | Reality |
| --- | --- | --- |
| `README.md:234` | `client → server: CHAT — data: string, relayed to partner` | **Removed in Phase 2.** `ALLOWED_RELAY` is `{SDP_OFFER, SDP_ANSWER, SDP_ICE_CANDIDATE}` (`main.py:60`); a `CHAT` frame is now silently dropped. Chat moved to the data channel |
| `README.md:217` | "`/ping` reports `"redis": false`" | The `redis` boolean was replaced by `mode` (`"in-memory"｜"redis"｜"redis-down"`) + `ready`. `main.py:423` even documents *why* the boolean was wrong — the README still described the wrong version |
| `README.md:5` | `**Live demo:** <link if you have one>` | Unfilled template placeholder on a live product |
| `README.md:6` | `**Design document (PDF):** /docs/Yawnfox-SDD.pdf` | **No `docs/` directory exists** |
| `README.md:12–21` | ToC links to `#getting-started`, `#limits-and-known-issues`, `#roadmap`, `#license` | **All four sections absent.** Four broken anchors out of eleven |

The README also never documented the mini-games, which are now a headline feature.

**MEDIUM — `frontend/README.md` was a stale truncated copy of the root README** ✅ **applied**
48 lines: identical title, tagline, the same broken demo/PDF links, the same 11-item ToC — then
it stopped mid-document after the Architecture diagram. Ten of its eleven ToC links pointed at
nothing. It documented the *backend*. It contained no frontend-specific information at all:
not `npm run dev`, not `VITE_API_DOMAIN`, not the SvelteKit/Tailwind/adapter setup. Whichever
README a new developer opened first, it was wrong.

**LOW — no `frontend/.env.example`** ✅ **applied**
`VITE_API_DOMAIN` was required to run the frontend and mentioned only in passing at
`README.md:153`. The backend, by contrast, has an *excellent* `.env.example` — every variable
in it was verified against `os.environ` usage and it is accurate and complete.

**LOW — `.env.example` documents `PORT`, which Python never reads** ⬜ **left as-is**
`grep os.environ backend/` confirms `PORT` is not read by the application. It's consumed by
`fly.toml [env]` and the `Procfile`; the **Dockerfile hardcodes `--port 8080`** and ignores it.
Since Fly deploys via the Dockerfile, setting `PORT` has no effect in production. Left alone
deliberately: the Procfile path does use it, so the variable is not purely fictional, and
changing the Dockerfile to honour `PORT` is a deployment change, not a doc fix.

**LOW — comments that no longer match their code** ✅ **partially applied**

- `peer.js:467` — `// keep your existing wakeup ping` above a function whose logic was
  unreachable — ✅ removed with the function
- `svelte.config.js:6-8` — three lines of adapter-auto boilerplate above an explicit
  `adapter-vercel` — ⬜ still open (cosmetic)
- `jsconfig.json` — retains the full generated comment block about path aliases — ⬜ still open

**LOW — UI text that contradicts the product** ✅ **applied**

- `+page.svelte:210` — the pre-chat modal promised *"You can hide messages or **block
  users**."* **There is no block feature.** This is the same gap the FAQ and both prior reviews
  flag as the #1 product risk, except here it was stated as a shipped capability the user was
  agreeing to. **This was a product-honesty issue, not a typo.** Replaced with
  *"You can hide messages or skip to the next person at any time."* — both of which are real,
  shipped features (the Messages toggle and the Next button).
- `+page.svelte:202` — *"Camera and microphone permissions required used."* (garbled) → fixed
- `faq/+page.svelte:76` — `<h1>` read **"Frequency Asked Questions"** → fixed
- `privacy/+page.svelte:29` and `tos/+page.svelte:29` —
  `Last updated: {new Date().toLocaleDateString()}` rendered **today's date on every page
  load**. A legal document that always claims it was updated today conveys no information and
  is arguably worse than no date. → hardcoded to the date the text actually last changed
  (2026-06-26), with a comment explaining why it must stay hardcoded
- `static/site.webmanifest` — `"name": ""`, `"short_name": ""`; the PWA install prompt showed a
  blank app name → filled in

---

### 2.5 Structural Concerns

**HIGH — `Game.svelte` is 868 lines and holds eight distinct responsibilities** ⬜ **still open**
Flagged at 800+ in the prior review; it has **grown**. It currently owns:

1. Two games' state machines (`phase` × `kind`)
2. The wire protocol — 8 message types, hand-dispatched in one `switch`
3. Invite/accept/decline/busy/camera-cancel negotiation
4. Face-tracking lifecycle (load, start, stop, baseline capture, re-zero on goal)
5. The 60fps physics + interpolation loop
6. All canvas rendering — `fitCanvas`, `draw`, `drawBall`, `drawPaddle`, `buildBallTile`
7. Sprite decode + rasterisation caching
8. ~150 lines of overlay UI (score, countdown, invite modal, notice toast, result card)

The natural seam is already visible and unexploited: `pong.js` and `tictactoe.js` prove pure
logic *can* be extracted here — both are clean, testable, and self-checking. Everything in the
list above could follow the same pattern.

**MEDIUM — `chat/+page.svelte` is 630 lines (was 504 in June)** ⬜ **still open**
Owns peer lifecycle, camera acquisition/release, topic chip editor, chat message log with
capacity rule, two layout modes, settings modal, and the entire control bar. The
`peerOptions()` factory is a genuinely good piece of design — one place for the callbacks, with
a comment explaining that both setup paths must use it. That instinct should be applied more
widely in this file.

**MEDIUM — the matcher lock serializes all pairing across the entire fleet** ⬜ **still open**
Not a bug, and correctness no longer depends on it (`_MATCH_LUA` is atomic — the code says so).
But it is a throughput ceiling that isn't written down anywhere. Using the arithmetic
`store.py:43-46` supplies itself (~5 ms Upstash RTT):

- One pair ≈ 1 `EVAL` + `set_partners` + up to 2 publishes ≈ **4 round-trips ≈ 20 ms**
- Only one instance holds `yf:matcher:lock` at a time → **~50 pairs/sec fleet-wide**,
  regardless of machine count
- At 5,000 concurrent users with a 30-second average session, sustained demand is
  ~83 pairs/sec

So `fly scale count N` scales connections and relay linearly, but **not matching.** Well inside
limits today; worth a comment in `matcher_loop()` and a metric before any growth push.

**MEDIUM — zero static type checking across ~3,100 lines of frontend JS** ⬜ **still open**
`jsconfig.json` sets `"checkJs": false`; `svelte-check` is not installed and there is no
`check` script. Nothing verifies that `peerOptions()`'s eleven callbacks match what
`PeerConnection` invokes, or that `Game.svelte`'s props line up with what `chat/+page.svelte`
passes. The backend has type hints throughout `store.py`; the frontend has JSDoc on four
functions and nothing enforcing any of it.

**LOW — onboarding friction** ✅ **largely applied**

What helps: outstanding backend comments, an excellent `backend/.env.example`, self-checking
pure modules, clean git history since June with descriptive conventional-commit messages.

What hurt, in order — and current status:

1. Two READMEs, both wrong, one a truncated copy of the other — ✅ fixed
2. `npm run lint` failed on a clean checkout — ✅ fixed (now exits 0)
3. No CI, so no executable definition of "green" — ✅ fixed
4. Running the backend tests required reading three docstrings and starting Redis on three
   different ports by hand — ✅ partially (CI runs `test_matcher.py`; the other two are
   documented in the README with copy-pasteable commands)
5. Two Svelte dialects with no stated preference — ⬜ open (documented in
   `frontend/README.md`, not resolved)
6. The 868-line and 630-line files are the two you must understand to change anything
   user-facing — ⬜ open

---

## 3. Quick Wins vs. Larger Refactors

### Quick wins — all 20 applied ✅

| # | Fix | Status |
| --- | --- | --- |
| 1 | `npx prettier --write .` → 7 files fixed | ✅ |
| 2 | Delete unused imports: `onMount` (`+page.svelte`), `tick` (`chat/+page.svelte`) | ✅ |
| 3 | Key the two `#each` blocks (`chat/+page.svelte`) | ✅ keyed by topic string (unique — `addTopic` dedupes case-insensitively) |
| 4 | Remove duplicate + misplaced `svelte-ignore` comments | ✅ |
| 5 | Replace `catch (_) {}` ×4 in `peer.js` with logged catches | ✅ clears 8 eslint errors |
| 6 | Delete `ensureServerAwake`'s dead branch, or the whole function | ✅ whole function removed |
| 7 | Delete `src/lib/index.js`, `static/spinner.svg`, `static/favicon copy.ico` | ✅ |
| 8 | `git rm --cached` the `.DS_Store` files + add a root `.gitignore` | ✅ |
| 9 | Fix "Frequency Asked Questions"; fix "permissions required used." | ✅ |
| 10 | **Remove the false "or block users" claim from the pre-chat modal** | ✅ |
| 11 | Replace `{new Date().toLocaleDateString()}` on `/privacy` + `/tos` | ✅ |
| 12 | Fill in `name` / `short_name` in `site.webmanifest` | ✅ |
| 13 | Delete `window.setAppState = setState` | ✅ |
| 14 | Make the `/ping` URL honour `VITE_API_DOMAIN`; delete the commented-out localhost line | ✅ resolved by #6 |
| 15 | Add `frontend/.env.example` | ✅ |
| 16 | README: fix the `CHAT` row, the `"redis": false` line, the broken ToC entries, the missing PDF link | ✅ |
| 17 | Replace `frontend/README.md` with a real frontend README | ✅ |
| 18 | Add a `ruff.toml` + exempt the intentional `main.py` E402s | ✅ used `per-file-ignores` (1 line) instead of 15 `# noqa` comments |
| 19 | Drop the 4 unused SvelteKit adapters | ✅ |
| 20 | Log the swallowed sends at `main.py:275,289` | ✅ |

Items 1–5 alone took `npm run lint` from **14 errors to 0**.

### Larger refactors — discuss before starting ⬜

| Refactor | Why | Risk |
| --- | --- | --- |
| **Split `Game.svelte` (868 → ~4 files)** | Extract canvas rendering (`draw`/`drawBall`/`drawPaddle`/`buildBallTile`/`fitCanvas` → `pongRender.js`), the wire protocol dispatch (→ `gameProtocol.js`, testable like `pong.js`), and the overlay UI (→ `GameOverlay.svelte`). Leaves a ~300-line coordinator | Medium — needs two-window playtesting to verify, which is exactly the manual step there's no test for |
| **Add `peer.js` self-checks** — *partly done, see §7* | Highest-value test gap in the repo. `tests/leak.spec.js` now covers the connection lifecycle in a real browser. Still uncovered: ICE queueing, the connect timeout, and the `PARTNER_LEFT`-while-connecting path — a `node`-runnable `demo()` with a fake `RTCPeerConnection`/`WebSocket` would reach those without a browser | Medium — needs mock scaffolding, which is the kind of thing that grows |
| **Pick one Svelte dialect** | Either migrate `+layout.svelte` back to legacy (1 line, consistent immediately) or commit to runes and convert the other four. **Recommend the 1-line version now**, full runes migration as its own tracked piece of work | Low if you go backwards; Medium forward |
| **Unify game input validation** | Validate `kind` against `['hockey','ttt']` on `game_invite`/`game_start`, matching the standard the other three message types already meet | Low — decide whether it's worth a shared validator or just two `includes()` checks |
| **Route the last `alert()` through the notice UI** | `peer.js:84` still uses a blocking native dialog for `RATE_LIMITED` / `SERVER_UNAVAILABLE`, which is what the rest of the UI was designed to avoid | Low — but crosses a component boundary |
| **Rename `nose.js` → `face.js`** | The module tracks a face bounding box, not a nose; ~15 call sites across two files. "Nose Hockey" stays as the product name | Low — purely mechanical, but touches two files broadly |
| **Make the other two backend suites CI-runnable** | Drop the hardcoded `venv/bin/uvicorn` path, have `test_multiprocess.py` start its own instances the way `test_redis_outage.py` already does, add a `requirements-dev.txt` | Low-Medium — mostly mechanical, and `test_redis_outage.py` is the working template |
| **Add `svelte-check`** | Zero static type checking across ~3,100 lines today | Low to add, Medium to get to zero errors |
| **Document / measure the matcher lock ceiling** | Add a comment stating the ~50 pairs/sec fleet-wide figure, and a metric on pairs-per-second. Sharding the lock is the eventual fix — **not needed now** | Low to document; do not shard speculatively |

---

## 4. What Was Already Fixed Since the Last Review

Each open item from both prior reports, checked against the code as of 2026-08-11.
**The recent work stuck.**

### ✅ Confirmed fixed before this audit

| Item | Flagged in | Verified |
| --- | --- | --- |
| **`tryHandle` swallowed async errors** | June §5, Aug §6 | **Fixed.** `peer.js` now `await callback()` with the comment explaining why. Commit `a1856df` |
| **Stuck pairs after a match with no handshake** | June §3, Aug §6 item 3 | **Fixed.** `CONNECT_TIMEOUT_MS = 15000` armed in `handlePartnerFound`, cleared by any `setState`, plus the `PARTNER_LEFT`-while-not-CONNECTED → `_connectFailed()` re-queue. Commit `a1856df` |
| **`Procfile` said `gunicorn app:app`** | June §1 | **Fixed.** Now `uvicorn main:app --ws-max-size 65536 --no-proxy-headers`, matching the Dockerfile |
| **SPOF: all state in process memory, no horizontal scale** | June §3 🔴 | **Fixed.** Full Redis migration — ZSET waiting pool, partner map, presence, pub/sub relay, cross-instance matcher lock. Verified by `test_multiprocess.py` |
| **`min_machines_running = 0`** → cold starts | June §3 | **Fixed.** `fly.toml` now `min_machines_running = 1`, `auto_stop_machines = 'suspend'` |
| **No rate limiting of any kind** | June §5 🔴 | **Fixed, twice over.** Sliding-window per-IP at connect **and** a per-socket token bucket for every subsequent frame. Commit `6850304` |
| **No WebSocket origin check** | June §5 🔴 | **Fixed.** `_origin_allowed()` rejects with 1008 before any work |
| **Unknown messages relayed verbatim, unbounded size** | June §5 🔴 | **Fixed.** `ALLOWED_RELAY` whitelist + `MAX_MESSAGE_BYTES = 65536` at the app layer *and* `--ws-max-size` at the protocol layer |
| **Spoofable `X-Forwarded-For`** | Aug §4 | **Fixed.** `fly-client-ip` preferred; XFF only when `TRUST_XFF=true` (default false) |
| **Zero tests** | June §5 🔴 | **Fixed.** 35 backend checks + 2 self-checking pure modules |
| **Matcher cost O(N); silently stopped pairing past ~200 stale entries** | Aug §4 | **Fixed.** Single atomic `_MATCH_LUA`; verified at 5,000 waiting |
| **Redis checked only at startup** | Aug §4 | **Fixed.** Continuous health tracking including a hung-server probe. Commit `f776f72` |
| **Heartbeat cost 3 commands/user/30s** | Aug §4 | **Fixed.** One `_REFRESH_LUA` EVAL covers all clients |
| **Camera re-opened on every "Next"** | Aug §4 | **Fixed.** One stream per session. Commit `2c62349` |
| **Emoji-only control buttons** | June §4 | **Fixed.** Lucide icons throughout |
| **Global `state_lock` contention on every relay** | June §3 | **Fixed.** The lock is gone |

### Closed by this audit ✅

| Item | Flagged in |
| --- | --- |
| **Dead `"waking up"` wake-up check** | June §3, Aug §6, Aug Rec §5 — open through two reviews, now removed |
| **No CI** | never previously flagged; was the thing keeping everything else from staying fixed |
| **`npm run lint` red** | new finding this audit |
| **False "block users" claim in the pre-chat modal** | new finding this audit |

### ⬜ Still open

| Item | Flagged in | Status |
| --- | --- | --- |
| **No TURN server** | June #2, Aug #1 | Unchanged — STUN only. Correctly triaged as top priority *when* strangers arrive |
| **No moderation / reporting / blocking** | June #1, Aug #2 | Unchanged. The modal no longer *claims* blocking exists, which was the immediate honesty problem — the feature gap remains |
| **Accessibility** | June §4, Aug §6 | Unchanged. The two *stale* suppressions were removed; the genuine ones remain |
| **No frontend E2E test** | Aug §6, Aug Rec §4 | **Partly closed** — `tests/leak.spec.js` (§7) drives two real browsers through match → chat → game → Next. Scoped to the connection lifecycle, not a general E2E suite, and not in CI |
| **Fire-and-forget `asyncio.create_task`** (`main.py:183,295`) | June §3 🟡 | **Still open.** Python's own docs warn these can be GC'd mid-flight |
| **`Game.svelte` too large** | prior review at 800+ | **Regressed** — now 868 lines |

---

## 5. Applied Changes (2026-08-11)

### Files changed

```
 .github/workflows/ci.yml                 |  83 ++++++++++  (new)
 .gitignore                               |   2 ++         (new)
 backend/ruff.toml                        |  14 ++         (new)
 frontend/.env.example                    |  13 ++         (new)
 README.md                                |  62 +++++--
 backend/main.py                          |  11 +-
 frontend/.prettierignore                 |   4 +
 frontend/README.md                       | 104 +++++-----
 frontend/package.json                    |   4 -
 frontend/src/lib/peer.js                 |  38 ++---
 frontend/src/routes/+page.svelte         |  31 ++--
 frontend/src/routes/chat/+page.svelte    |   9 +-
 frontend/src/routes/faq/+page.svelte     |  72 ++++++--
 frontend/src/routes/privacy/+page.svelte |  84 ++++++---
 frontend/src/routes/tos/+page.svelte     |  70 +++++---
 frontend/static/site.webmanifest         |  12 +-
 frontend/svelte.config.js                |   2 +-
 .DS_Store, backend/.DS_Store             |  untracked
 frontend/src/lib/index.js                |  deleted (empty)
 frontend/static/spinner.svg              |  deleted (unreferenced)
 frontend/static/favicon copy.ico         |  deleted (unreferenced)
```

Most of the line counts on the `.svelte` pages are `prettier --write` reflowing long
attribute lists, not logic changes.

### Three judgement calls worth flagging

1. **Item 6 — deleted the whole `ensureServerAwake` function, not just its dead branch.**
   The `sessionStorage` throttle it guarded was written *only inside* the dead branch, so the
   throttle was dead too. What remained was "fetch `/ping`, parse, discard" on every
   connection. Removing it also removed the last hardcoded `api.yawnfox.com` URL, which
   resolved item 14 at the same time. **Behavioural note:** the signaling WebSocket now opens
   without waiting on a `/ping` round-trip first. Safe because `min_machines_running = 1`
   keeps a machine warm, and Fly starts a suspended machine on any incoming connection —
   including the WebSocket itself. Net effect is a slightly *faster* first connect.

2. **Item 18 — used `[lint.per-file-ignores]` instead of 15 `# noqa: E402` comments.**
   One config line with an explanation beats fifteen inline suppressions. Verified the
   exemption is scoped to `main.py` only: `ruff --isolated --select E402` still reports all
   15 findings there and none elsewhere, so E402 detection stays live for the rest of the
   codebase.

3. **Item 1 — added `static/models/` to `.prettierignore` rather than reformatting it.**
   `tiny_face_detector_model-weights_manifest.json` is a vendored face-api artifact.
   Reformatting a third-party file creates diff noise and makes it harder to verify against
   upstream.

### CI workflow

`.github/workflows/ci.yml`, on push to `main` and on every PR. Two jobs:

**`frontend`** — Node 20, `npm ci` with lockfile caching, then:

- `npm run lint` (`prettier --check .` then `eslint .`)
- `node src/lib/pong.js`
- `node src/lib/tictactoe.js`

**`backend`** — Python 3.11 (matching `backend/Dockerfile`), pip caching, with a
`redis:7-alpine` service container health-checked on `redis-cli ping` and mapped `6390:6379`
(6390 is the port `test_matcher.py` defaults to), then:

- `pipx run ruff check .`
- `python tests/test_matcher.py` with `REDIS_URL=redis://localhost:6390`

`test_multiprocess.py` and `test_redis_outage.py` are **not** run in CI, and the workflow says
why in a trailing comment: the first needs two uvicorn instances started by hand, and the
second hardcodes `backend/venv/bin/uvicorn` and `SIGSTOP`s a real `redis-server`. Making them
CI-runnable is listed as a refactor in §3.

### Verification — everything run locally after the changes

| Check | Result |
| --- | --- |
| `npm run lint` | ✅ **exit 0** — "All matched files use Prettier code style", eslint silent (was 14 errors + 7 prettier failures) |
| `node src/lib/pong.js` | ✅ exit 0 — "all checks passed" |
| `node src/lib/tictactoe.js` | ✅ exit 0 — "all checks passed" |
| `ruff check .` (backend, project config) | ✅ exit 0 — "All checks passed", 5 Python files linted |
| `tests/test_matcher.py` | ✅ **12 passed, 0 failed** |
| `tests/test_multiprocess.py` | ✅ **12 passed, 0 failed** (two live instances on shared Redis) |
| `tests/test_redis_outage.py` | ✅ **11 passed, 0 failed** (incl. hung-Redis detection in 10.0s) |
| `npm run build` | ✅ succeeds with `adapter-vercel` after removing the 4 unused adapters |

**Total: 35/35 backend checks, 2/2 frontend self-checks, lint clean, build green.**

Committed as `d6a615e` and pushed to `main`. GitHub Actions run #1: **green**, both jobs, every
step — including the Redis service container the workflow depends on.

---

## 6. Recommended Next Steps

Nothing below is urgent at current usage. In order:

1. ~~Commit and let CI run~~ — **done.** `d6a615e`, run #1 green.
2. ~~Add `peer.js` coverage~~ — **partly done.** `tests/leak.spec.js` (§7) now covers the
   connection lifecycle end to end in a real browser. The *handshake* logic — ICE queueing,
   `_remoteDescSet` gating, the 15s connect deadline — is still untested.
3. **Fix the two findings §7 left open**: the `startNoseTracking` cold-cache race and
   `waitForWebSocketOpen` never rejecting. Both small, both pre-existing.
4. **Split `Game.svelte`.** It regressed past its previous flag; the extraction seams are
   already obvious and `pong.js`/`tictactoe.js` are the working template.
5. **Pick one Svelte dialect** — one line if you standardise on legacy.
6. **Add a TURN relay** (from the prior reviews — still the top *product* risk once real
   strangers arrive).
7. **Minimum viable safety: report + block.** Note the pre-chat modal no longer promises
   blocking, so the immediate honesty problem is closed — but the FAQ still promises a
   reporting system that does not exist.

---

## 7. Follow-up: connection leak in `peer.js` (2026-08-11)

Investigated after this audit, on the question of whether extended sessions (video + text chat +
mini-games, with repeated "Next") leak. **They did.** This turned out to be the most serious
defect found anywhere in this document, and §2.3's warning that "the entire frontend interaction
layer is untested, and it is where the risk now lives" was pointing directly at it.

Fixed in `4181d3c`, with a regression test.

### What was wrong

Every "Next" **initiated by the other side** abandoned a fully live `PeerConnection`. Four
defects in `peer.js`, all feeding one another:

| # | Defect | Effect |
| --- | --- | --- |
| 1 | `oniceconnectionstatechange` / `onconnectionstatechange` announced `DISCONNECTED_REMOTE` via bare `setState` instead of `disconnect()` | That announcement makes the chat page build a *replacement* peer, so announcing it without tearing down orphans the old one fully alive |
| 2 | `disconnect()` had no idempotence guard | Both handlers fire for one transition, and the data channel's `close` event re-entered `disconnect()` after it had nulled everything — so one disconnection ran teardown 2–3× and built 2–3 replacement peers |
| 3 | `disconnect()` never released `options` | Those callbacks close over the page component, so one retained peer pinned the whole graph — both video elements, the message list, the `Game` instance |
| 4 | The signaling socket was only `close()`d when `readyState === OPEN`, but dereferenced either way | A socket still CONNECTING was dropped without closing, and the HTML spec forbids collecting a CONNECTING/OPEN socket that still has listeners |

### Why this was a privacy problem, not just a memory one

This is the part that matters. An orphaned peer was **still connected to the live UI**, because
defect 3 meant it never let go of the page's callbacks — while its data channel stayed open.

A previous partner could therefore still:

- **inject chat messages** into your conversation with your *next* partner
  (`onChatMessage` → `addMessage`)
- **drive a running mini-game** (`onGameMessage` → `gameRef.handleMessage`)
- **flip the camera-off indicator** (`onRemoteCamState`)
- **replace your view of the new partner** (`ontrack` → `remoteVideo.srcObject`)

None of that requires the old partner to do anything unusual — it is simply what the abandoned
object was still wired to.

Separately, and more conditionally: the `RTCPeerConnection` was never `close()`d, so its senders
stayed attached to the live camera/mic stream and kept transmitting to the previous partner for
as long as their end stayed up. Whether they were still receiving depends on how they left, so
this is stated as a real exposure rather than a certainty in every case — unlike the inbound
direction above, which was unconditional.

It also caused a **correctness** bug with no memory component at all: an orphan kept its armed
15-second connect deadline, and on firing called `onConnectFailed` on the page — disconnecting
the current, healthy conversation.

### How it was measured

Heap deltas were the wrong instrument — too noisy. The decisive metric is a whole number:
*how many `RTCPeerConnection`s did the app open and never close?*

`frontend/tests/leak.spec.js` drives two real browsers through N rounds of
match → chat message → X / O → **B presses Next**. B leaves deliberately: that puts A on the
*remote* disconnect path. Pressing Next yourself takes a different, simpler branch — which is
exactly why this survived manual testing for so long.

Instrumentation wraps the `RTCPeerConnection` and `WebSocket` constructors from the test via
`page.addInitScript`, so **nothing in `src/` is modified** and the shipping code is what gets
measured. Sockets are filtered by URL to exclude Vite's HMR socket.

### Results — 20 cycles

| | Before | After |
| --- | --- | --- |
| `RTCPeerConnection` constructed | 41 (**2.05/cycle**) | 21 (1.05/cycle) |
| …still open on page A | **21** | **1** ✅ |
| Signaling sockets still open | 21 | 1 ✅ |
| Backend `/ping` `connections` | **22** (clean = 2) | **2** ✅ |
| JS heap | 7,783 → 8,405 KB | 7,789 → 8,375 KB |
| face-detection failures | 0 | 0 |

The signatures were dead clean and matched the code review exactly: `pcTotal` climbing by
precisely 2 per cycle (defect 2, the double `createPeer()`) and `pcLive` by precisely 1
(defect 1, one peer orphaned alive). The backend corroborated it independently — 22 live sockets
where there should be 2. **At Fly's 250-connection-per-machine limit, one user doing 20 Nexts was
consuming 22 slots.**

Heap growth was modest because the connections themselves, not JS objects, were the real cost —
and the probe holds strong references, so even that figure is understated.

### Confirmed clean by the same investigation

- **No TensorFlow.js tensor leak.** Verified from library source: `detectSingleFace` disposes
  everything via `tf.tidy` plus explicit `.dispose()` of `out`/`out0` and the three tensors
  `extractBoxes` returns; `FaceDetection` holds plain numbers, no tensor. **No `tf.tidy()` is
  needed in `nose.js`.** There *is* an un-`finally`'d disposal on the error path in
  `TinyYolov2Base.detect`, which `nose.js` would amplify by swallowing and retrying at 30 Hz —
  but its precondition is detectable for free via the `face detection failed` warning, and zero
  occurred across both runs.
- **`Game.svelte` was clean.** `ResizeObserver`, `matchMedia`, the `timers` array, the rAF loop
  and `buildBallTile` all correctly torn down or bounded. The earlier suspicion about
  `buildBallTile` allocating a canvas per resize was unfounded — it replaces, it does not
  accumulate.
- **`messages`** capped at 20 *and* cleared on every re-match, as §2.1 recorded.

### Still open from this investigation

- **`Game.svelte:447` `startNoseTracking()` race.** Awaits `loadNose()` then assigns `stopNose`
  without checking whether one is already set. Two in-flight calls can both pass the `phase`
  guard, and the second assignment discards the first stop function — orphaning a 30 Hz
  detection loop forever. Only reachable on a **cold model cache**, where the ~1.5 MB load
  outlasts a full stop/restart cycle. Highest CPU/GPU cost of anything here if it triggers.
- **`chat/+page.svelte:208` `waitForWebSocketOpen()` never rejects.** No `error`/`close` path,
  so a socket that never opens leaves the promise pending forever and `createPeer()` never
  returns.

### The test harness

`npm run test:leak` (`CYCLES=50 npm run test:leak` for a longer soak). ~1.4 min for 20 cycles.

**Deliberately not in CI** — it needs the backend venv, ports 8000 and 5173, and two real
browsers, which is too heavy for a per-push job. The reasoning is recorded in the file header.
It asserts the counts stay flat, so it fails loudly if this regresses.

One safety note worth keeping: the Playwright config forces `REDIS_URL=''` for the backend it
starts, so the harness can never join the production matchmaking pool regardless of what
`backend/.env` contains — the failure mode `backend/.env.example` explicitly warns about.

---

*Audit performed 2026-08-11. §1–§4 describe the codebase as found. §5 records the 20 quick-win
fixes and the CI workflow (`d6a615e`). §7 records a follow-up leak investigation and its fix
(`4181d3c`). All changes are committed and pushed to `main`; CI green on both.*
