<script>
	let showConsent = false;

	function agreeAndContinue() {
		window.location.href = '/chat';
	}
</script>

<div class="flex min-h-screen flex-col bg-gray-900 text-white lg:flex-row">
	<!-- Left Side: Branding & CTA -->
	<div
		class="mx-auto flex max-w-xl flex-col items-start justify-center space-y-10 px-8 py-12 lg:w-1/2"
	>
		<!-- Branding -->
		<div class="flex items-center space-x-4">
			<img
				src="/icon.png"
				alt="Yawnfox Logo"
				class="h-16 w-16 rounded-xl shadow-lg sm:h-20 sm:w-20"
			/>
			<h1 class="text-4xl font-extrabold leading-tight tracking-tight sm:text-5xl">
				<span class="text-yellow-400">Yawnfox</span> <span class="text-white">🎥</span>
			</h1>
		</div>

		<!-- Tagline -->
		<p class="text-lg leading-relaxed text-gray-300 sm:text-xl">
			Chat with strangers instantly. No login, no clutter — just anonymous face-to-face video
			conversations.
		</p>

		<!-- CTA Button -->
		<div class="flex flex-col space-y-4 sm:flex-row sm:items-center sm:space-x-4 sm:space-y-0">
			<button
				on:click={() => (showConsent = true)}
				class="rounded-xl bg-yellow-400 px-6 py-3 text-lg font-semibold text-black shadow-md transition hover:scale-105 hover:bg-yellow-300"
			>
				Start Chatting
			</button>

			<!-- Donate Link -->
			<a
				href="https://buymeacoffee.com/overcaffdev"
				target="_blank"
				class="rounded-md bg-yellow-400 px-5 py-2.5 text-sm font-semibold text-black shadow transition hover:scale-105 hover:bg-yellow-300"
			>
				Tip / Donate
			</a>
		</div>

		<!-- Footer -->
		<footer class="w-full pt-8 text-sm text-gray-500">
			<div class="flex flex-wrap items-center gap-6">
				<a href="/tos" class="transition hover:text-white">Terms</a>
				<a href="/privacy" class="transition hover:text-white">Privacy</a>
			</div>
			<p class="mt-4 text-xs">© {new Date().getFullYear()} Yawnfox. All rights reserved.</p>
		</footer>
	</div>

	<!-- Right Side: FAQ & Info Card -->
	<div
		class="relative flex items-center justify-center bg-gradient-to-br from-gray-800 to-gray-900 px-6 py-12 lg:w-1/2"
	>
		<div
			class="w-full max-w-2xl space-y-6 rounded-2xl border border-white/10 bg-white/5 p-6 shadow-2xl backdrop-blur-md sm:p-8"
		>
			<h2 class="text-2xl font-bold text-white sm:text-3xl">Why Yawnfox?</h2>

			<!-- Section 1 -->
			<div>
				<h3 class="mb-2 text-lg font-semibold text-yellow-400">What is Yawnfox?</h3>
				<p class="text-sm leading-relaxed text-gray-200 sm:text-base">
					Yawnfox is your minimalist alternative to Omegle. No accounts, no tracking, just instant
					video chats with strangers — totally free.
				</p>
			</div>

			<!-- Section 2 -->
			<div>
				<h3 class="mb-2 text-lg font-semibold text-yellow-400">How is it different?</h3>
				<p class="text-sm leading-relaxed text-gray-200 sm:text-base">
					No ads, no captchas, and no clutter. Yawnfox focuses on speed, privacy, and one-click
					video chatting without the junk.
				</p>
			</div>
		</div>
	</div>
</div>

<!-- Consent Modal -->
{#if showConsent}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
		<div
			class="w-[90%] max-w-sm space-y-4 rounded-2xl bg-white p-6 text-center text-black shadow-2xl backdrop-blur-lg"
		>
			<h2 class="text-xl font-semibold">Do you agree to our Terms?</h2>
			<p class="text-sm text-gray-600">
				To use Yawnfox, you must agree to our
				<a href="/tos" class="font-medium text-indigo-600 hover:underline">Terms of Service</a> and
				<a href="/privacy" class="font-medium text-indigo-600 hover:underline">Privacy Policy</a>.
			</p>
			<div class="mt-4 flex justify-center gap-4">
				<button
					class="rounded bg-gray-100 px-4 py-2 text-black hover:bg-gray-200"
					on:click={() => (showConsent = false)}
				>
					Cancel
				</button>
				<button
					class="rounded bg-yellow-400 px-4 py-2 font-semibold text-black hover:bg-yellow-300"
					on:click={agreeAndContinue}
				>
					I Agree
				</button>
			</div>
		</div>
	</div>
{/if}
