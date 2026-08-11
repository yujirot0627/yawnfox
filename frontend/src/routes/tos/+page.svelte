<script>
	import { ArrowLeft } from 'lucide-svelte';
</script>

<svelte:head>
	<title>Terms of Service - Yawnfox</title>
	<meta
		name="description"
		content="Yawnfox Terms of Service. Read our terms for using the random video chat platform."
	/>
	<link rel="canonical" href="https://yawnfox.com/tos" />
	<meta property="og:title" content="Terms of Service - Yawnfox" />
	<meta
		property="og:description"
		content="Yawnfox Terms of Service. Read our terms for using the random video chat platform."
	/>
	<meta property="og:url" content="https://yawnfox.com/tos" />
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
			<h1 class="mb-4 text-4xl font-bold text-white">Terms of Service</h1>
			<!-- Hardcoded on purpose: this must state when the terms actually changed,
			     not when the page was rendered. Update it when you edit the text below. -->
			<p class="text-sm text-gray-500">Last updated: 26 June 2026</p>
		</header>

		<!-- Content Sections -->
		<div class="space-y-12 text-lg leading-relaxed">
			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">1. Acceptance of Terms</h2>
				<p>
					By accessing or using Yawnfox, you agree to be bound by these Terms. If you do not agree
					to these terms, please do not use our services.
				</p>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">2. Eligibility</h2>
				<p>
					You must be at least <strong>18 years old</strong> to use this platform. By using Yawnfox,
					you represent and warrant that you meet this age requirement.
				</p>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">3. User Conduct</h2>
				<p class="mb-4">We prioritize a safe and respectful environment. You agree NOT to:</p>
				<ul class="list-disc space-y-2 pl-6 marker:text-yellow-400">
					<li>Harass, abuse, or threaten others.</li>
					<li>Share sexually explicit, violent, or illegal content.</li>
					<li>Record or distribute conversations without consent.</li>
					<li>Use the platform for spam or solicitation.</li>
				</ul>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">4. Content & Responsibility</h2>
				<p>
					You are solely responsible for your interactions. Yawnfox does not monitor every
					conversation in real-time and assumes no liability for user-generated content.
				</p>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">5. Account Termination</h2>
				<p>
					We reserve the right to ban or suspend access to any user who violates these terms,
					without prior notice.
				</p>
			</section>

			<section>
				<h2 class="mb-4 text-2xl font-bold text-white">6. Disclaimer</h2>
				<p class="text-gray-400 italic">
					The service is provided "as is" without warranties of any kind. We are not responsible for
					connection issues or the actions of other users.
				</p>
			</section>
		</div>
	</main>
</div>
