<script>
	import { onMount } from 'svelte';

	let showConfirmation = false;
	let skipNextTime = false;

	function handleStart() {
		const storedSkip = localStorage.getItem('yawnfox_skip_intro');
		if (storedSkip === 'true') {
			window.location.href = '/chat';
		} else {
			showConfirmation = true;
		}
	}

	function proceedToChat() {
		if (skipNextTime) {
			localStorage.setItem('yawnfox_skip_intro', 'true');
		}
		window.location.href = '/chat';
	}
</script>

<svelte:head>
	<title>Yawnfox - Anonymous Video Chat</title>
	<meta name="description" content="Instant topic-based video chat with strangers. No login required, anonymous by default. Match based on shared interests or go random." />
	<link rel="canonical" href="https://yawnfox.com/" />
	<meta property="og:title" content="Yawnfox - Anonymous Video Chat" />
	<meta property="og:description" content="Chat with strangers instantly via video. Add topics to find matches or go random." />
	<meta property="og:url" content="https://yawnfox.com/" />
	<meta property="og:type" content="website" />
	<meta name="twitter:card" content="summary_large_image" />
	<script type="application/ld+json">
		{
			"@context": "https://schema.org",
			"@type": "WebSite",
			"name": "Yawnfox",
			"url": "https://yawnfox.com/",
			"description": "Anonymous topic-based video chat platform."
		}
	</script>
</svelte:head>

<div
	class="min-h-screen bg-gray-900 font-sans text-white selection:bg-yellow-400 selection:text-black"
>
	<!-- Navbar (Minimal) -->
	<nav class="absolute top-0 z-10 flex w-full items-center justify-between px-6 py-6">
		<!-- Brand Icon (Optional, minimal) -->
		<div
			class="flex h-14 w-14 items-center justify-center rounded-full border border-white/15 bg-white/10 shadow-sm"
		>
			<img src="/icon.png" alt="Yawnfox" class="h-9 w-9 rounded-full opacity-95" />
		</div>
		<!-- Menu (Optional placeholder) -->
		<!-- <button class="text-gray-400 hover:text-white">Menu</button> -->
	</nav>

	<!-- HERO SECTION (Above the fold) -->
	<header
		class="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-gray-900 px-4 text-center"
	>
		<!-- Background Image -->
		<img
			src="/Yawn_BG.png"
			alt="Background"
			class="absolute inset-0 z-0 h-full w-full object-cover object-center"
		/>

		<!-- Solid Overlay -->
		<div class="absolute inset-0 z-0 bg-black/45"></div>

		<div class="relative z-10 mx-auto max-w-3xl space-y-8">
			<h1 class="mb-2 text-6xl font-black tracking-tight text-white drop-shadow-lg sm:text-8xl">
				YawnFox
			</h1>
			<p class="text-xl font-light tracking-wide text-gray-200 drop-shadow-md sm:text-2xl">
				Pick a topic. Get matched.
			</p>

			<div class="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
				<button
					on:click={handleStart}
					class="w-full rounded-full bg-yellow-400 px-10 py-4 text-lg font-bold tracking-wide text-black shadow-xl transition-all hover:scale-105 hover:bg-yellow-300 sm:w-auto"
				>
					VIDEO CHAT
				</button>
				<a
					href="#about"
					class="w-full rounded-full border border-white/30 bg-black/20 px-10 py-4 font-medium text-white backdrop-blur-sm transition hover:bg-white/10 sm:w-auto"
				>
					LEARN MORE
				</a>
			</div>

			<p class="pt-4 text-sm font-medium text-gray-300 drop-shadow">
				Add up to 3 topics or go random.
			</p>
		</div>
	</header>

	<!-- SECTION A: WHAT IS YAWNFOX? -->
	<section id="about" class="border-t border-white/5 bg-gray-900/30 px-6 py-20">
		<div class="mx-auto max-w-2xl space-y-6 text-center">
			<h2 class="text-3xl font-bold text-white">What is Yawnfox?</h2>
			<p class="text-lg leading-relaxed text-gray-400">
				Yawnfox is a simple, anonymous video chat platform. We connect you with strangers based on
				shared interests instantly. No accounts, no login, just conversation.
			</p>
		</div>
	</section>

	<!-- SECTION B: WHY YAWNFOX? -->
	<section class="px-6 py-20">
		<div class="mx-auto max-w-4xl">
			<h2 class="mb-12 text-center text-3xl font-bold text-white">Why it's better</h2>
			<div class="grid grid-cols-1 gap-8 sm:grid-cols-2">
				<div class="rounded-2xl border border-white/10 bg-white/5 p-6">
					<h3 class="mb-2 text-xl font-semibold text-yellow-400">Topic Matching</h3>
					<p class="text-gray-400">
						Add interests to find people who actually want to talk about what you do.
					</p>
				</div>
				<div class="rounded-2xl border border-white/10 bg-white/5 p-6">
					<h3 class="mb-2 text-xl font-semibold text-yellow-400">Privacy-First</h3>
					<p class="text-gray-400">Your privacy is our top priority.</p>
				</div>
				<div class="rounded-2xl border border-white/10 bg-white/5 p-6">
					<h3 class="mb-2 text-xl font-semibold text-yellow-400">Anonymous by Default</h3>
					<p class="text-gray-400">No accounts required to start chatting.</p>
				</div>
				<div class="rounded-2xl border border-white/10 bg-white/5 p-6">
					<h3 class="mb-2 text-xl font-semibold text-yellow-400">Overlay Messages</h3>
					<p class="text-gray-400">
						See chat messages right over the video, keeping the focus on the face.
					</p>
				</div>
			</div>
		</div>
	</section>

	<!-- SECTION C: HOW IT WORKS -->
	<section class="border-t border-white/5 bg-gray-900/30 px-6 py-20">
		<div class="mx-auto max-w-4xl text-center">
			<h2 class="mb-12 text-3xl font-bold text-white">How it works</h2>
			<div class="flex flex-col items-center justify-center gap-8 md:flex-row md:gap-12">
				<div class="max-w-xs">
					<div class="mb-4 text-4xl">🏷️</div>
					<h3 class="text-lg font-bold">1. Add Topics</h3>
					<p class="mt-2 text-sm text-gray-500">Optional. Enter up to 3 interests.</p>
				</div>
				<div class="hidden text-2xl text-gray-600 md:block">→</div>
				<div class="max-w-xs">
					<div class="mb-4 text-4xl">⚡</div>
					<h3 class="text-lg font-bold">2. Start Matching</h3>
					<p class="mt-2 text-sm text-gray-500">One click to find a partner.</p>
				</div>
				<div class="hidden text-2xl text-gray-600 md:block">→</div>
				<div class="max-w-xs">
					<div class="mb-4 text-4xl">🎥</div>
					<h3 class="text-lg font-bold">3. Chat</h3>
					<p class="mt-2 text-sm text-gray-500">Video + Text. Skip anytime.</p>
				</div>
			</div>
		</div>
	</section>

	<!-- SECTION D: SAFETY -->
	<footer class="border-t border-white/5 px-6 py-12 text-center">
		<div class="mx-auto max-w-xl space-y-4">
			<p class="font-medium text-gray-400">Be respectful and enjoy!</p>
			<div class="flex justify-center gap-6 text-sm text-gray-600">
				<a href="/faq" class="hover:text-gray-400">FAQ</a>
				<a href="/tos" class="hover:text-gray-400">Terms</a>
				<a href="/privacy" class="hover:text-gray-400">Privacy</a>
			</div>
			<p class="mt-8 text-xs text-gray-700">© {new Date().getFullYear()} Yawnfox</p>
		</div>
	</footer>

	<!-- Confirmation Modal -->
	{#if showConfirmation}
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="animate-in fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-md duration-200"
			on:click={() => (showConfirmation = false)}
		>
			<div
				class="relative w-full max-w-sm overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 p-6 shadow-2xl"
				on:click|stopPropagation
			>
				<h2 class="mb-4 text-center text-xl font-bold text-white">Ready to start?</h2>

				<ul class="mb-6 space-y-3 text-sm text-gray-300">
					<li class="flex items-start gap-3">
						<span class="text-yellow-400">•</span>
						<span>Camera and microphone permissions required used.</span>
					</li>
					<li class="flex items-start gap-3">
						<span class="text-yellow-400">•</span>
						<span>Be respectful.</span>
					</li>
					<li class="flex items-start gap-3">
						<span class="text-yellow-400">•</span>
						<span>You can hide messages or block users.</span>
					</li>
				</ul>

				<label class="mb-6 flex cursor-pointer select-none items-center gap-2">
					<input
						type="checkbox"
						bind:checked={skipNextTime}
						class="rounded border-gray-600 bg-gray-800 text-yellow-500 focus:ring-yellow-500/50"
					/>
					<span class="text-xs text-gray-500 transition hover:text-gray-400">Don't show again</span>
				</label>

				<div class="flex flex-col gap-3">
					<button
						on:click={proceedToChat}
						class="w-full rounded-xl bg-yellow-400 py-3 font-bold text-black shadow-lg shadow-yellow-400/10 transition hover:bg-yellow-300"
					>
						Enter video chat
					</button>
					<button
						on:click={() => (showConfirmation = false)}
						class="w-full py-2 text-sm text-gray-500 transition hover:text-white"
					>
						Cancel
					</button>
				</div>
			</div>
		</div>
	{/if}
</div>
