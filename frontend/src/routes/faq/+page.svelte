<script>
	import { ArrowLeft, MessageCircle } from 'lucide-svelte';
</script>

<svelte:head>
	<title>FAQ - Yawnfox Random Video Chat</title>
	<meta
		name="description"
		content="Frequently asked questions about Yawnfox. Learn how anonymous video chat, topic matching, and privacy work on Yawnfox."
	/>
	<link rel="canonical" href="https://yawnfox.com/faq" />
	<meta property="og:title" content="FAQ - Yawnfox Random Video Chat" />
	<meta
		property="og:description"
		content="Frequently asked questions about Yawnfox. Learn how anonymous video chat, topic matching, and privacy work on Yawnfox."
	/>
	<meta property="og:url" content="https://yawnfox.com/faq" />
	<meta name="twitter:title" content="FAQ - Yawnfox Random Video Chat" />
	<meta
		name="twitter:description"
		content="Frequently asked questions about Yawnfox. Learn how anonymous video chat, topic matching, and privacy work on Yawnfox."
	/>
	<script type="application/ld+json">
		{
			"@context": "https://schema.org",
			"@type": "FAQPage",
			"mainEntity": [
				{
					"@type": "Question",
					"name": "Is Yawnfox really anonymous?",
					"acceptedAnswer": {
						"@type": "Answer",
						"text": "Yes. Yawnfox is designed to be usable without an account. We don't ask for your name, email, or phone number. Interactions happen directly between users."
					}
				},
				{
					"@type": "Question",
					"name": "How does topic matching work?",
					"acceptedAnswer": {
						"@type": "Answer",
						"text": "It's simple: if you enter a topic (like \"anime\" or \"coding\") and someone else enters the same (or similar) topic, our system prioritizes connecting you two. If no match is found, you connect with a random stranger."
					}
				},
				{
					"@type": "Question",
					"name": "How do I hide messages?",
					"acceptedAnswer": {
						"@type": "Answer",
						"text": "Tap the chat icon in the control bar to toggle the message overlay on or off."
					}
				},
				{
					"@type": "Question",
					"name": "Nothing happens when I click Start?",
					"acceptedAnswer": {
						"@type": "Answer",
						"text": "Make sure you have allowed Camera and Microphone permissions in your browser. Yawnfox needs these to establish a video call."
					}
				},
				{
					"@type": "Question",
					"name": "How do I report someone?",
					"acceptedAnswer": {
						"@type": "Answer",
						"text": "If a user violates our terms (nudity, harassment), please leave the chat immediately. We are working on a more robust reporting system for future updates."
					}
				}
			]
		}
	</script>
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

	<main class="mx-auto max-w-3xl px-6 pb-24">
		<header class="mb-12 border-b border-white/10 pb-8">
			<h1 class="mb-4 text-4xl font-bold text-white">Frequently Asked Questions</h1>
		</header>

		<div class="space-y-8">
			<article>
				<h3 class="mb-2 text-xl font-bold text-white">Is Yawnfox really anonymous?</h3>
				<p>
					Yes. Yawnfox is designed to be usable without an account. We don't ask for your name,
					email, or phone number. Interactions happen directly between users.
				</p>
			</article>

			<article>
				<h3 class="mb-2 text-xl font-bold text-white">How does topic matching work?</h3>
				<p>
					It's simple: if you enter a topic (like "anime" or "coding") and someone else enters the
					same (or similar) topic, our system prioritizes connecting you two. If no match is found,
					you connect with a random stranger.
				</p>
			</article>

			<article>
				<h3 class="mb-2 text-xl font-bold text-white">How do I hide messages?</h3>
				<p>
					Tap the <MessageCircle class="inline h-4 w-4 align-text-bottom" /> icon in the control bar
					to toggle the message overlay on or off.
				</p>
			</article>

			<article>
				<h3 class="mb-2 text-xl font-bold text-white">Nothing happens when I click Start?</h3>
				<p>
					Make sure you have allowed Camera and Microphone permissions in your browser. Yawnfox
					needs these to establish a video call.
				</p>
			</article>

			<article>
				<h3 class="mb-2 text-xl font-bold text-white">How do I report someone?</h3>
				<p>
					If a user violates our terms (nudity, harassment), please leave the chat immediately. We
					are working on a more robust reporting system for future updates.
				</p>
			</article>
		</div>
	</main>
</div>
