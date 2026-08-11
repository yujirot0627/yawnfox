<script>
	import { ArrowLeft } from 'lucide-svelte';
</script>

<svelte:head>
	<title>Privacy Policy - Yawnfox</title>
	<meta
		name="description"
		content="Yawnfox Privacy Policy. Learn how we protect your anonymity on our random video chat platform."
	/>
	<link rel="canonical" href="https://yawnfox.com/privacy" />
	<meta property="og:title" content="Privacy Policy - Yawnfox" />
	<meta
		property="og:description"
		content="Yawnfox Privacy Policy. Learn how we protect your anonymity on our random video chat platform."
	/>
	<meta property="og:url" content="https://yawnfox.com/privacy" />
</svelte:head>

<div
	class="min-h-screen bg-gray-900 font-sans text-gray-300 selection:bg-yellow-400 selection:text-black"
>
	<!-- Navbar / Back Link -->
	<nav
		class="sticky top-0 z-10 mb-8 w-full border-b border-white/5 bg-gray-900/90 px-6 py-4 backdrop-blur-md"
	>
		<div class="mx-auto flex max-w-3xl items-center">
			<a
				href="/"
				class="flex items-center gap-2 text-sm font-medium text-gray-400 transition hover:text-white"
			>
				<ArrowLeft class="h-4 w-4" /> Back to Home
			</a>
		</div>
	</nav>

	<!-- Main Content -->
	<main class="mx-auto max-w-3xl px-6 pb-24">
		<!-- Header -->
		<header class="mb-12 border-b border-white/10 pb-8">
			<h1 class="mb-4 text-4xl font-bold text-white">Privacy Policy</h1>
			<!-- Hardcoded on purpose: this must state when the policy actually changed,
			     not when the page was rendered. Update it when you edit the text below. -->
			<p class="text-sm text-gray-500">Last updated: 26 June 2026</p>
		</header>

		<!-- Content Sections -->
		<div class="space-y-12 text-lg leading-relaxed">
			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">1. Our Commitment</h2>
				<p>
					Yawnfox is designed to prioritize your privacy and anonymity. We are committed to ensuring
					a safe and respectful video chat experience without collecting unnecessary data.
				</p>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">2. Data We Do NOT Collect</h2>
				<ul class="list-disc space-y-2 pl-6 marker:text-yellow-400">
					<li>
						<strong>No PII:</strong> We do not ask for or store your name, email, phone number, or location.
					</li>
					<li>
						<strong>No Logs:</strong> We do not record or store video/audio of your conversations.
					</li>
					<li>
						<strong>No Tracking:</strong> We do not use persistent cookies to track your behavior across
						sites.
					</li>
				</ul>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">3. Peer-to-Peer Connection</h2>
				<p>
					Video and audio streams are transmitted directly between users (peer-to-peer). Our servers
					help establish the connection but do not process or store the stream content.
				</p>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">4. Community Guidelines</h2>
				<p class="mb-4">To keep Yawnfox safe, the following are strictly prohibited:</p>
				<ul class="list-disc space-y-2 pl-6 marker:text-yellow-400">
					<li>Nudity or sexually explicit content.</li>
					<li>Harassment, bullying, or hate speech.</li>
					<li>Recording partners without explicit consent.</li>
				</ul>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">5. Changes to Policy</h2>
				<p>
					We may update this policy periodically. Continued use of the platform signifies your
					acceptance of any changes.
				</p>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">6. Contact</h2>
				<p>
					If you have questions about privacy, please check our <a
						href="/"
						class="text-yellow-400 hover:text-yellow-300">About</a
					> info or reach out through our support channels.
				</p>
			</section>
		</div>
	</main>
</div>
