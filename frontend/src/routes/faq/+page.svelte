<script>
</script>

<svelte:head>
	<title>FAQ - Yawnfox</title>
	<meta name="description" content="Frequently asked questions about Yawnfox. Learn about anonymous video chat, safety, topic matching, and troubleshooting." />
	<link rel="canonical" href="https://yawnfox.com/faq" />
	<script type="application/ld+json">
		{
			"@context": "https://schema.org",
			"@type": "FAQPage",
			"mainEntity": [
				{
					"@type": "Question",
					"name": "Is Yawnfox anonymous?",
					"acceptedAnswer": {
						"@type": "Answer",
						"text": "Yes. We do not require registration, and we do not store personal information like names or emails."
					}
				},
				{
					"@type": "Question",
					"name": "Are topics required?",
					"acceptedAnswer": {
						"@type": "Answer",
						"text": "No. You can add topics to match with people sharing similar interests, or skip them to match randomly."
					}
				},
				{
					"@type": "Question",
					"name": "Do you record chats?",
					"acceptedAnswer": {
						"@type": "Answer",
						"text": "No. Yawnfox facilitates peer-to-peer connections. We do not record or store user video streams."
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
				<span>←</span> Back to Home
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
				<p>Tap the 💬 icon in the control bar to toggle the message overlay on or off.</p>
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
