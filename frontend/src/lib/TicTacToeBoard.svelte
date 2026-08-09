<script>
	import { createEventDispatcher } from 'svelte';
	import { X } from '$lib/tictactoe.js';

	export let board = Array(9).fill(null);
	export let myMark = X;
	export let myTurn = false;
	export let winLine = null; // number[] of the winning cells, or null

	const dispatch = createEventDispatcher();

	// Presentational only — Game.svelte owns the rules and decides what is legal.
	const isWinning = (i) => !!winLine?.includes(i);
</script>

<div class="pointer-events-auto flex flex-col items-center gap-4">
	<p
		class="text-sm font-medium tracking-wide text-white/90 drop-shadow-[0_1px_3px_rgba(0,0,0,0.9)]"
	>
		You are
		<span class={myMark === X ? 'font-bold text-yellow-400' : 'font-bold text-white'}>{myMark}</span
		>
		&middot;
		{#if winLine}
			<span class="text-white/60">Game over</span>
		{:else if myTurn}
			<span class="font-bold text-yellow-400">Your turn</span>
		{:else}
			<span class="text-white/60">Stranger's turn</span>
		{/if}
	</p>

	<!-- Faint tint only, no backdrop-blur: the video must stay readable through it. -->
	<div class="grid grid-cols-3 gap-2 rounded-2xl bg-black/20 p-2 shadow-2xl">
		{#each board as cell, i (i)}
			<button
				on:click={() => dispatch('move', i)}
				disabled={!myTurn || cell !== null || !!winLine}
				aria-label={cell ? `Cell ${i + 1}, ${cell}` : `Cell ${i + 1}, empty`}
				class="flex h-20 w-20 items-center justify-center rounded-xl border-2 shadow-lg transition sm:h-24 sm:w-24
					{isWinning(i) ? 'border-yellow-400 bg-yellow-400/30' : 'border-white/50 bg-black/25'}
					{!cell && myTurn && !winLine
					? 'cursor-pointer hover:border-yellow-400/80 hover:bg-black/40 active:scale-95'
					: 'cursor-default'}"
			>
				{#if cell === X}
					<!-- Inline so the mark can inherit currentColor; an <img> could not recolour. -->
					<svg
						viewBox="0 0 24 24"
						class="h-10 w-10 text-yellow-400 drop-shadow-[0_2px_4px_rgba(0,0,0,0.9)] sm:h-12 sm:w-12"
						fill="none"
						stroke="currentColor"
						stroke-width="3"
						stroke-linecap="round"
						aria-hidden="true"
					>
						<path d="M5 5 L19 19 M19 5 L5 19" />
					</svg>
				{:else if cell}
					<svg
						viewBox="0 0 24 24"
						class="h-10 w-10 text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.9)] sm:h-12 sm:w-12"
						fill="none"
						stroke="currentColor"
						stroke-width="3"
						aria-hidden="true"
					>
						<circle cx="12" cy="12" r="7" />
					</svg>
				{/if}
			</button>
		{/each}
	</div>
</div>
