<script lang="ts">
	import { toast, type Toast } from '$lib/stores/toast';
	import { Check, X, AlertTriangle, AlertCircle, Info } from 'lucide-svelte';

	let toasts = $state<Toast[]>([]);

	$effect(() => {
		const unsubscribe = toast.subscribe((value) => {
			toasts = value;
		});
		return () => unsubscribe();
	});

	function getIconComponent(type: Toast['type']) {
		switch (type) {
			case 'success':
				return Check;
			case 'error':
				return AlertCircle;
			case 'warning':
				return AlertTriangle;
			default:
				return Info;
		}
	}

	function getColorClass(type: Toast['type']) {
		switch (type) {
			case 'success':
				return 'bg-success';
			case 'error':
				return 'bg-error';
			case 'warning':
				return 'bg-warning';
			default:
				return 'bg-info';
		}
	}

	function getTextClass(type: Toast['type']) {
		switch (type) {
			case 'success':
				return 'text-success-foreground';
			case 'error':
				return 'text-error-foreground';
			case 'warning':
				return 'text-warning-foreground';
			default:
				return 'text-info-foreground';
		}
	}
</script>

{#if toasts.length > 0}
	<div class="fixed bottom-4 right-4 z-50 space-y-2">
		{#each toasts as t (t.id)}
			<div
				class="flex items-center gap-3 px-4 py-3 rounded-lg shadow-modal {getColorClass(t.type)} {getTextClass(t.type)} animate-slide-in-right"
			>
				<svelte:component this={getIconComponent(t.type)} size={20} strokeWidth={2.5} />
				<span>{t.message}</span>
				<button
					onclick={() => toast.dismiss(t.id)}
					class="ml-2 opacity-70 hover:opacity-100 flex items-center justify-center"
					aria-label="닫기"
				>
					<X size={18} />
				</button>
			</div>
		{/each}
	</div>
{/if}
