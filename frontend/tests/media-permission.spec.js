/**
 * Camera/mic failure handling: the right message per cause, and a way back.
 *
 * getUserMedia is stubbed to throw specific error names, because headless
 * Chromium cannot produce a genuine permission denial — it throws
 * NotSupportedError instead of NotAllowedError, so the real branches would
 * never be reached. What is under test is our mapping and recovery, not the
 * browser's prompt.
 *
 * Fast (~5s) and deterministic: only the frontend is needed, no matching, no
 * second browser. Unlike leak.spec.js this could reasonably go in CI.
 *
 *   npm run test:media
 */
import { test, expect } from '@playwright/test';

/** Replace getUserMedia with one that throws `name`, and stub the Permissions API. */
const stub = (name, permissionState) => `
  window.__failWith = ${JSON.stringify(name)};
  navigator.mediaDevices.getUserMedia = async () => {
    if (!window.__failWith) return await window.__realGUM.call(navigator.mediaDevices, {video:true, audio:true});
    const e = new Error('stubbed'); e.name = window.__failWith; throw e;
  };
  navigator.permissions.query = async (d) =>
    d && d.name === 'camera'
      ? { state: ${JSON.stringify(permissionState)} }
      : { state: 'granted' };
`;

const open = async (browser, name, permissionState) => {
	const ctx = await browser.newContext({ permissions: ['camera', 'microphone'] });
	const page = await ctx.newPage();
	await page.addInitScript(`window.__realGUM = navigator.mediaDevices.getUserMedia;`);
	await page.addInitScript(stub(name, permissionState));
	await page.goto('/chat');
	return { ctx, page };
};

test('NotAllowedError + Permissions API says denied -> blocked instructions at once', async ({
	browser
}) => {
	const { ctx, page } = await open(browser, 'NotAllowedError', 'denied');
	await expect(page.getByText(/Camera and microphone access was blocked/)).toBeVisible();
	await expect(page.getByText(/browser is blocking access/i)).toBeVisible();
	await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
	console.log('\n>>> hard block: honest message + settings instructions + Retry');
	await ctx.close();
});

test('NotAllowedError with no Permissions API -> instructions only on 2nd denial', async ({
	browser
}) => {
	const ctx = await browser.newContext({ permissions: ['camera', 'microphone'] });
	const page = await ctx.newPage();
	await page.addInitScript(`window.__realGUM = navigator.mediaDevices.getUserMedia;`);
	await page.addInitScript(`
    ${stub('NotAllowedError', 'denied')}
    navigator.permissions.query = async () => { throw new TypeError('unsupported'); };
  `);
	await page.goto('/chat');

	await expect(page.getByText(/Camera and microphone access was blocked/)).toBeVisible();
	await expect(page.getByText(/browser is blocking access/i)).toHaveCount(0);
	console.log('\n>>> 1st denial: no premature "go to settings" advice');

	await page.getByRole('button', { name: 'Retry' }).click();
	await expect(page.getByText(/browser is blocking access/i)).toBeVisible();
	console.log('>>> 2nd denial: instructions appear (Safari/Firefox fallback works)');
	await ctx.close();
});

test('NotFoundError -> says no device, not "permission denied"', async ({ browser }) => {
	const { ctx, page } = await open(browser, 'NotFoundError', 'granted');
	await expect(page.getByText(/No camera or microphone found/)).toBeVisible();
	await expect(page.getByText(/blocked|denied/i)).toHaveCount(0);
	console.log('\n>>> missing device reported honestly (was "permission denied" before)');
	await ctx.close();
});

test('NotReadableError -> says device is in use', async ({ browser }) => {
	const { ctx, page } = await open(browser, 'NotReadableError', 'granted');
	await expect(page.getByText(/already in use by another app/)).toBeVisible();
	console.log('\n>>> busy device reported honestly');
	await ctx.close();
});

test('Retry recovers without a page reload once permission is granted', async ({ browser }) => {
	const { ctx, page } = await open(browser, 'NotAllowedError', 'denied');
	await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();

	// Grant it, exactly as a user changing browser settings would.
	await page.evaluate(() => {
		window.__failWith = null;
	});
	await page.getByRole('button', { name: 'Retry' }).click();

	// Session actually starts: Start button appears, no reload happened.
	await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeVisible({
		timeout: 20_000
	});
	console.log('\n>>> Retry started the session with no page reload — the whole point');
	await ctx.close();
});
