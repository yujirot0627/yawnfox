<script>
	import '../app.css';

	let { children } = $props();
</script>

<svelte:head>
	<title>Yawnfox – Omegle Alternative for Anonymous Video Chat</title>

	<!-- Global social defaults (per-page title/description/og live in each page) -->
	<meta property="og:type" content="website" />
	<meta name="twitter:card" content="summary_large_image" />
	<meta property="og:image" content="https://yawnfox.com/android-chrome-512x512.png" />
	<meta name="twitter:image" content="https://yawnfox.com/android-chrome-512x512.png" />

	<!-- Favicon -->
	<link rel="icon" href="/icon.png" />
</svelte:head>

{@render children()}
