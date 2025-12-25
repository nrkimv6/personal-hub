<script lang="ts">
	import { toast, type Toast } from '$lib/stores/toast';

	let toasts = $state<Toast[]>([]);

	$effect(() => {
		const unsubscribe = toast.subscribe((value) => {
			toasts = value;
		});
		return () => unsubscribe();
	});

	function getIcon(type: Toast['type']) {
		switch (type) {
			case 'success':
				return '✓';
			case 'error':
				return '✕';
			case 'warning':
				return '⚠';
			default:
				return 'ℹ';
		}
	}

	function getColorClass(type: Toast['type']) {
		switch (type) {
			case 'success':
				return 'bg-green-500';
			case 'error':
				return 'bg-red-500';
			case 'warning':
				return 'bg-yellow-500';
			default:
				return 'bg-blue-500';
		}
	}
</script>

{#if toasts.length > 0}
	<div class="fixed bottom-4 right-4 z-50 space-y-2">
		{#each toasts as t (t.id)}
			<div
				class="flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg text-white {getColorClass(
					t.type
				)} animate-slide-in"
			>
				<span class="font-bold">{getIcon(t.type)}</span>
				<span>{t.message}</span>
				<button
					onclick={() => toast.dismiss(t.id)}
					class="ml-2 opacity-70 hover:opacity-100"
					aria-label="닫기"
				>
					✕
				</button>
			</div>
		{/each}
	</div>
{/if}

<style>
	@keyframes slide-in {
		from {
			transform: translateX(100%);
			opacity: 0;
		}
		to {
			transform: translateX(0);
			opacity: 1;
		}
	}

	.animate-slide-in {
		animation: slide-in 0.3s ease-out;
	}
</style>
