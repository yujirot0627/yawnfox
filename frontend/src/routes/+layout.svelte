<script>
	import '../app.css';

	let { children } = $props();
</script>

<svelte:head>
	<title>Yawnfox – Omegle Alternative for Anonymous Video Chat</title>
	<meta name="description" content="Yawnfox is a modern Omegle alternative for anonymous video chat. No login, no signup, just meet random strangers instantly." />
	
	<meta property="og:title" content="Yawnfox – Omegle Alternative" />
	<meta property="og:description" content="Looking for an Omegle replacement? Try Yawnfox — anonymous video chat with strangers. Fun, safe, and no signup needed." />
	
	<meta name="twitter:title" content="Yawnfox – Omegle Alternative for Video Chat" />
	<meta name="twitter:description" content="Chat with strangers anonymously like on Omegle. Try Yawnfox — modern, simple, no hassle." />

	<!-- Favicon -->
	<link rel="icon" href="/icon.png" />
</svelte:head>

{@render children()}
