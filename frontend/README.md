# Yawnfox — frontend

SvelteKit app for [yawnfox.com](https://yawnfox.com). Handles the UI, the WebRTC
peer connection, and the two mini-games. For the backend, deployment, and the
signaling protocol, see the [root README](../README.md).

## Running locally

```bash
npm install
cp .env.example .env   # then point VITE_API_DOMAIN at your backend
npm run dev
```

The backend must be running separately (`cd ../backend && uvicorn main:app --port 8080`).
With `REDIS_URL` unset it runs in in-memory mode, so no Redis is needed for local work.

## Scripts

| Command           | What it does                                                           |
| ----------------- | ---------------------------------------------------------------------- |
| `npm run dev`     | Vite dev server                                                        |
| `npm run build`   | Production build (adapter-vercel, `nodejs20.x`)                        |
| `npm run preview` | Serve the production build locally                                     |
| `npm run lint`    | `prettier --check .` then `eslint .` — **must be clean; CI runs this** |
| `npm run format`  | `prettier --write .`                                                   |

## Configuration

One variable, documented in [`.env.example`](.env.example):

| Variable          | Description                                                                                                                   |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `VITE_API_DOMAIN` | Host[:port] of the signaling backend, **no scheme**. `peer.js` picks `ws://` or `wss://` to match the page it is served from. |

## Layout

```
src/
  routes/
    +layout.svelte        global meta / OG tags
    +page.svelte          landing page + pre-chat confirmation modal
    chat/+page.svelte     the video chat screen (peer lifecycle, chat, topics, layout)
    faq|tos|privacy/      static content pages
  lib/
    peer.js               WebRTC + signaling WebSocket state machine
    Game.svelte           mini-game host: invite flow, loop, canvas, overlay UI
    pong.js               pure Nose Hockey physics      — self-checking
    tictactoe.js          pure X / O rules              — self-checking
    nose.js               face-box tracking (face-api), drives the paddles
    TicTacToeBoard.svelte presentational board
static/
  models/                 vendored face-api detector weights (~190 KB)
```

## Self-checks

`pong.js` and `tictactoe.js` are pure modules with a built-in assert-based
`demo()`. Run them directly — they exit non-zero on failure and CI runs both:

```bash
node src/lib/pong.js
node src/lib/tictactoe.js
```

There is no browser-level test yet. The WebRTC state machine in `peer.js`, the
camera lifecycle, and the game invite flow are all verified by hand with two
browser windows.

## Notes for anyone changing this

- **The camera stream is acquired once per visit** and shared by every
  `PeerConnection`. `disconnect()` must never call `stop()` on its tracks —
  only `releaseLocalMedia()` in the page's `onDestroy` may. Ignoring this
  re-introduces the blinking-camera bug.
- **Svelte 5 is installed, but only `+layout.svelte` uses runes.** Everything
  else is legacy syntax (`export let`, `on:click`, `$:`). Match the file you
  are editing rather than mixing dialects within one component.
- `Game.svelte` (~865 lines) owns two games with two different sync models:
  Nose Hockey is host-authoritative, X / O is replicated with both peers
  validating through the shared `canPlay()`. Know which one you are touching.
