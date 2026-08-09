// Face tracking for the mini game. Wraps @vladmandic/face-api (the maintained
// face-api.js fork).
//
// Imported dynamically so tfjs (~1MB) and the model (~190KB in static/models/)
// are only fetched when someone actually starts a game, never on a plain video chat.
//
// Only the detector runs — no landmark network. The paddle follows the centre of
// the face bounding box, which is both steadier than a single landmark and about
// twice as fast to compute, since the 68-point net no longer runs every frame.

let faceapi;
let loading; // memoised so two rapid game starts don't load the model twice

// Cap the sample rate so detection cannot starve the 60fps render loop on a
// phone. Slower devices simply fall short of this and add no extra delay.
const TARGET_HZ = 30;
const TARGET_PERIOD_MS = 1000 / TARGET_HZ;
const STATS_EVERY_MS = 5000;

const clamp01 = (v) => Math.max(0, Math.min(1, v));

export async function loadNose() {
	if (!loading) {
		loading = (async () => {
			// Explicit browser ESM build: the package's `main` points at the Node build,
			// which drags @tensorflow/tfjs-node into the SSR bundle for no reason.
			faceapi = await import('@vladmandic/face-api/dist/face-api.esm.js');
			await faceapi.tf.ready();
			await faceapi.nets.tinyFaceDetector.loadFromUri('/models');
		})().catch((err) => {
			loading = null; // let a later attempt retry rather than failing forever
			throw err;
		});
	}
	return loading;
}

/**
 * Poll `video` for the centre of the user's face.
 * Calls onPos({x, y}) normalised to 0..1, or onPos(null) when no face is visible
 * (camera off, user out of frame).
 *
 * x is MIRRORED. face-api reads the raw camera frame, but the preview is shown
 * flipped (`-scale-x-100`), so raw x runs opposite to what the player sees.
 * Mirroring here means moving your head right moves the paddle right.
 * Returns a stop function.
 */
export function trackFace(video, onPos) {
	// inputSize must be a multiple of 32. 128 is faster than 160 and the loss of
	// precision barely matters for a coarse box (it mattered for a landmark).
	const opts = new faceapi.TinyFaceDetectorOptions({ inputSize: 128, scoreThreshold: 0.4 });
	let stopped = false;

	// Rolling stats so the sample rate can be confirmed with real numbers.
	let samples = 0;
	let totalMs = 0;
	let windowStart = performance.now();

	(async () => {
		while (!stopped) {
			const started = performance.now();
			try {
				if (video?.videoHeight) {
					const det = await faceapi.detectSingleFace(video, opts);
					if (stopped) break;
					// relativeBox is already normalised to the frame, so no division by
					// the video dimensions is needed.
					const b = det?.relativeBox;
					onPos(
						b
							? {
									x: clamp01(1 - (b.x + b.width / 2)), // mirrored, see above
									y: clamp01(b.y + b.height / 2)
								}
							: null
					);
				} else {
					onPos(null);
				}
			} catch (err) {
				console.warn('face detection failed', err);
				onPos(null);
			}

			const elapsed = performance.now() - started;
			samples += 1;
			totalMs += elapsed;
			if (performance.now() - windowStart >= STATS_EVERY_MS) {
				const secs = (performance.now() - windowStart) / 1000;
				console.log(
					`🙂 face detection: ${(samples / secs).toFixed(1)} Hz, ` +
						`${(totalMs / samples).toFixed(1)} ms/frame`
				);
				samples = 0;
				totalMs = 0;
				windowStart = performance.now();
			}

			// Pace against the time already spent, rather than sleeping a flat amount
			// on top of it — the old fixed delay made the real period detection+delay.
			await new Promise((r) => setTimeout(r, Math.max(0, TARGET_PERIOD_MS - elapsed)));
		}
	})();

	return () => {
		stopped = true;
	};
}
