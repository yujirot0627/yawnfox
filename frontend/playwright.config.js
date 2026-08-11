import { defineConfig } from '@playwright/test';

// Harness for tests/leak.spec.js. Not part of `npm run lint`'s remit and not
// wired into CI — this drives two real browsers against a real backend, which
// is too heavy for a per-push job. Run it by hand: `npm run test:leak`.
export default defineConfig({
	testDir: 'tests',
	// Two browser contexts talking to each other; parallelism would make them
	// match with the wrong partner.
	workers: 1,
	fullyParallel: false,
	reporter: 'list',
	timeout: 15 * 60 * 1000,

	use: {
		baseURL: 'http://localhost:5173',
		launchOptions: {
			args: [
				// Synthetic camera/mic so getUserMedia resolves headlessly, and no
				// permission prompt to click through.
				'--use-fake-device-for-media-stream',
				'--use-fake-ui-for-media-stream'
			]
		}
	},

	webServer: [
		{
			// REDIS_URL is forced empty so this can never join the production
			// matchmaking pool, whatever backend/.env happens to contain. Empty
			// selects in-memory mode (store.py `_inmemory_mode`), and dotenv does
			// not override a variable already present in the environment.
			command: './venv/bin/uvicorn main:app --port 8000',
			cwd: '../backend',
			url: 'http://localhost:8000/ping',
			env: { REDIS_URL: '' },
			reuseExistingServer: true,
			stdout: 'ignore',
			timeout: 60 * 1000
		},
		{
			// Port 8000 matches VITE_API_DOMAIN in frontend/.env.local, so no env
			// override is needed here.
			command: 'npm run dev -- --port 5173 --strictPort',
			url: 'http://localhost:5173',
			reuseExistingServer: true,
			stdout: 'ignore',
			timeout: 120 * 1000
		}
	]
});
