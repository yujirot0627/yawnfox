<script>
	import { ArrowLeft, MessageCircle } from 'lucide-svelte';
</script>

<svelte:head>
	<title>FAQ - Yawnfox Random Video Chat</title>
	<meta name="description" content="Frequently asked questions about Yawnfox. Learn how anonymous video chat, topic matching, and privacy work on Yawnfox." />
	<link rel="canonical" href="https://yawnfox.com/faq" />
	<meta property="og:title" content="FAQ - Yawnfox Random Video Chat" />
	<meta property="og:description" content="Frequently asked questions about Yawnfox. Learn how anonymous video chat, topic matching, and privacy work on Yawnfox." />
	<meta property="og:url" content="https://yawnfox.com/faq" />
	<meta name="twitter:title" content="FAQ - Yawnfox Random Video Chat" />
	<meta name="twitter:description" content="Frequently asked questions about Yawnfox. Learn how anonymous video chat, topic matching, and privacy work on Yawnfox." />
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

<div class="min-h-screen bg-gray-900 text-gray-300 font-sans selection:bg-yellow-400 selection:text-black">
	<!-- Navbar / Back Link -->
	<nav class="sticky top-0 z-10 w-full bg-gray-900/90 backdrop-blur-md border-b border-white/5 py-4 px-6 mb-8">
		<div class="max-w-3xl mx-auto flex items-center">
			<a href="/" class="text-sm font-medium text-gray-400 hover:text-white transition flex items-center gap-2">
<ArrowLeft class="h-4 w-4" /> Back to Home
			</a>
		</div>
	</nav>

	<main class="max-w-3xl mx-auto px-6 pb-24">
		<header class="mb-12 border-b border-white/10 pb-8">
			<h1 class="text-4xl font-bold text-white mb-4">Frequency Asked Questions</h1>
		</header>

		<div class="space-y-8">
			<article>
				<h3 class="text-xl font-bold text-white mb-2">Is Yawnfox really anonymous?</h3>
				<p>Yes. Yawnfox is designed to be usable without an account. We don't ask for your name, email, or phone number. Interactions happen directly between users.</p>
			</article>

			<article>
				<h3 class="text-xl font-bold text-white mb-2">How does topic matching work?</h3>
				<p>It's simple: if you enter a topic (like "anime" or "coding") and someone else enters the same (or similar) topic, our system prioritizes connecting you two. If no match is found, you connect with a random stranger.</p>
			</article>

			<article>
				<h3 class="text-xl font-bold text-white mb-2">How do I hide messages?</h3>
				<p>Tap the <MessageCircle class="inline h-4 w-4 align-text-bottom" /> icon in the control bar to toggle the message overlay on or off.</p>
			</article>

			<article>
				<h3 class="text-xl font-bold text-white mb-2">Nothing happens when I click Start?</h3>
				<p>Make sure you have allowed Camera and Microphone permissions in your browser. Yawnfox needs these to establish a video call.</p>
			</article>

			<article>
				<h3 class="text-xl font-bold text-white mb-2">How do I report someone?</h3>
				<p>If a user violates our terms (nudity, harassment), please leave the chat immediately. We are working on a more robust reporting system for future updates.</p>
			</article>
		</div>
	</main>
</div>
