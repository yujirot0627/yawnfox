<script>
	let showConsent = false;

	function agreeAndContinue() {
		// Navigate only after agreement
		window.location.href = '/chat';
	}
</script>

<div class="min-h-screen bg-gradient-to-br from-purple-800 to-indigo-900 flex items-center justify-center px-4 text-white">
	<div class="flex flex-col items-center text-center space-y-6 max-w-xl">
		<!-- Logo -->
		<img src="/icon.png" alt="Yawnfox Logo" class="w-24 h-24 sm:w-28 sm:h-28 mb-2 rounded-xl shadow-lg" />

		<!-- Heading -->
		<h1 class="text-4xl sm:text-5xl font-extrabold tracking-tight">
			Welcome to <span class="text-yellow-400">yawnfox</span> 🎥
		</h1>

		<!-- Tagline -->
		<p class="text-lg text-gray-200 max-w-md">
			Yawnfox is your lightweight alternative to Omegle — anonymous video chat with strangers, no login required. Instant, fun, and totally free.
		</p>

		<!-- Start Chatting Button -->
		<button
			on:click={() => (showConsent = true)}
			class="mt-4 bg-yellow-400 text-black font-semibold text-lg px-6 py-3 rounded-xl shadow hover:bg-yellow-300 transition duration-200"
		>
			Start Chatting
		</button>

		<!-- Support Us -->
		<div class="mt-6 text-sm text-gray-300 max-w-xs text-center">
			<p class="mb-2">
				🙏 Help us keep Yawnfox free and running smoothly for everyone.
			</p>
			<a
				href="https://buymeacoffee.com/overcaffdev" 
				target="_blank" 
				class="inline-block mt-2 bg-yellow-400 text-black px-4 py-2 rounded-lg font-semibold shadow hover:bg-yellow-300 transition"
			>
				Tip / Donate
			</a>
		</div>

		<!-- SEO Bonus: Omegle FAQ section -->
		<!-- SEO Bonus: Omegle FAQ section -->
<div class="mt-12 w-full max-w-2xl bg-white/5 rounded-2xl p-6 sm:p-8 backdrop-blur-sm shadow-lg border border-white/10">
	<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">Yawnfox vs. Omegle</h2>

	<!-- What is Yawnfox -->
	<div class="mb-6">
		<h3 class="text-lg font-semibold text-yellow-400 mb-2">What is Yawnfox?</h3>
		<p class="text-sm sm:text-base text-gray-200 leading-relaxed">
			Yawnfox is a free, lightweight alternative to Omegle for anonymous video chats. No accounts, no tracking — just meet new people instantly, face-to-face.
		</p>
	</div>

	<!-- Difference from Omegle -->
	<div>
		<h3 class="text-lg font-semibold text-yellow-400 mb-2">How is Yawnfox different from Omegle?</h3>
		<p class="text-sm sm:text-base text-gray-200 leading-relaxed">
			Unlike Omegle, Yawnfox has no ads, no captchas, and no clutter. It's designed for speed, privacy, and a smooth one-click connection experience.
		</p>
	</div>
</div>


		<!-- Footer Links -->
		<!-- Footer Links -->
<footer class="mt-12 pt-6 border-t border-white/10 w-full text-center text-sm text-gray-400">
	<div class="flex justify-center space-x-6">
		<a href="/tos" class="hover:text-white transition-colors duration-200">Terms of Service</a>
		<a href="/privacy" class="hover:text-white transition-colors duration-200">Privacy Policy</a>
	</div>
	<p class="mt-4 text-xs text-gray-500">© {new Date().getFullYear()} Yawnfox. All rights reserved.</p>
</footer>

	</div>
</div>

{#if showConsent}
	<div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
		<div class="bg-white text-black rounded-xl p-6 w-[90%] max-w-sm shadow-lg space-y-4 text-center">
			<h2 class="text-xl font-semibold">Do you agree to our Terms?</h2>
			<p class="text-sm text-gray-600">
				To use Yawnfox, you must agree to our
				<a href="/tos" class="text-indigo-600 hover:underline font-medium">Terms of Service</a> and
				<a href="/privacy" class="text-indigo-600 hover:underline font-medium">Privacy Policy</a>.
			</p>
			<div class="flex justify-center gap-4 mt-4">
				<button
					class="bg-gray-200 hover:bg-gray-300 text-black px-4 py-2 rounded"
					on:click={() => (showConsent = false)}
				>
					Cancel
				</button>
				<button
					class="bg-yellow-400 hover:bg-yellow-300 text-black px-4 py-2 rounded font-semibold"
					on:click={agreeAndContinue}
				>
					I Agree
				</button>
			</div>
		</div>
	</div>
{/if}
