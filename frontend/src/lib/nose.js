// Nose tracking for the mini game. Wraps @vladmandic/face-api (the maintained
// face-api.js fork — same API, same weight format).
//
// Imported dynamically so tfjs (~1MB) and the models (~270KB in static/models/)
// are only fetched when someone actually starts a game, never on a plain video chat.

let faceapi;
let loading; // memoised so two rapid game starts don't load the models twice

const clamp01 = (v) => Math.max(0, Math.min(1, v));

export async function loadNose() {
	if (!loading) {
		loading = (async () => {
			// Explicit browser ESM build: the package's `main` points at the Node build,
			// which drags @tensorflow/tfjs-node into the SSR bundle for no reason.
			faceapi = await import('@vladmandic/face-api/dist/face-api.esm.js');
			await faceapi.tf.ready();
			await Promise.all([
				faceapi.nets.tinyFaceDetector.loadFromUri('/models'),
				faceapi.nets.faceLandmark68TinyNet.loadFromUri('/models')
			]);
		})().catch((err) => {
			loading = null; // let a later attempt retry rather than failing forever
			throw err;
		});
	}
	return loading;
}

/**
 * Poll `video` for the user's nose tip.
 * Calls onPos({x, y}) with the nose tip normalised to 0..1, or onPos(null) when
 * no face is visible (camera off, user out of frame).
 *
 * x is MIRRORED. face-api reads the raw camera frame, but the preview is shown
 * flipped (`-scale-x-100`), so raw x runs opposite to what the player sees.
 * Mirroring here means moving your head right moves the paddle right.
 * Returns a stop function.
 */
export function trackNose(video, onPos, intervalMs = 80) {
	// inputSize must be a multiple of 32; 160 keeps detection at ~12fps on a laptop
	// while the game renders at 60 and interpolates between samples.
	const opts = new faceapi.TinyFaceDetectorOptions({ inputSize: 160, scoreThreshold: 0.4 });
	let stopped = false;

	(async () => {
		while (!stopped) {
			try {
				if (video?.videoHeight) {
					const det = await faceapi.detectSingleFace(video, opts).withFaceLandmarks(true);
					if (stopped) break;
					// 68-point model: index 30 is the nose tip, which getNose() returns at index 3
					// (it covers points 27..35).
					const tip = det?.landmarks?.getNose?.()[3];
					const w = det?.landmarks?.imageWidth || video.videoWidth;
					const h = det?.landmarks?.imageHeight || video.videoHeight;
					onPos(
						tip && w && h
							? { x: clamp01(1 - tip.x / w), y: clamp01(tip.y / h) } // x mirrored, see above
							: null
					);
				} else {
					onPos(null);
				}
			} catch (err) {
				console.warn('nose detection failed', err);
				onPos(null);
			}
			await new Promise((r) => setTimeout(r, intervalMs));
		}
	})();

	return () => {
		stopped = true;
	};
}
