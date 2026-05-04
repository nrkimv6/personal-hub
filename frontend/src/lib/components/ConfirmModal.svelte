<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { confirmState, resolveConfirm, type ConfirmRequest } from '$lib/stores/confirm';

	let request = $state<ConfirmRequest | null>(null);
	let dialogElement = $state<HTMLElement | null>(null);

	const unsubscribe = confirmState.subscribe((value) => {
		request = value;
	});

	function close(confirmed: boolean) {
		resolveConfirm(confirmed);
	}

	function handleKeydown(event: KeyboardEvent) {
		if (!request) return;
		if (event.key === 'Escape') {
			event.preventDefault();
			close(false);
		}
	}

	function confirmButtonClass(variant: ConfirmRequest['variant']): string {
		switch (variant) {
			case 'danger':
				return 'bg-destructive text-white hover:bg-destructive/90';
			case 'warning':
				return 'bg-warning text-warning-foreground hover:bg-warning/90';
			default:
				return 'bg-primary text-white hover:bg-primary-hover';
		}
	}

	$effect(() => {
		if (request && dialogElement) {
			dialogElement.focus();
		}
	});

	onMount(() => {
		window.addEventListener('keydown', handleKeydown);
	});

	onDestroy(() => {
		window.removeEventListener('keydown', handleKeydown);
		unsubscribe();
	});
</script>

{#if request}
	<div class="fixed inset-0 z-[80] flex items-center justify-center px-4">
		<button
			type="button"
			class="absolute inset-0 z-0 cursor-default bg-black/50"
			aria-label="확인 모달 닫기"
			onclick={() => close(false)}
		></button>
		<div
			bind:this={dialogElement}
			class="relative z-10 w-full max-w-md rounded-lg border border-border bg-card p-5 text-card-foreground shadow-xl focus:outline-none"
			role="dialog"
			aria-modal="true"
			aria-labelledby="confirm-modal-title"
			aria-describedby="confirm-modal-message"
			tabindex="-1"
		>
			<h2 id="confirm-modal-title" class="text-base font-semibold text-foreground">
				{request.title}
			</h2>
			<p id="confirm-modal-message" class="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
				{request.message}
			</p>
			<div class="mt-5 flex justify-end gap-2">
				<button
					type="button"
					class="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
					onclick={() => close(false)}
				>
					{request.cancelText}
				</button>
				<button
					type="button"
					class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors {confirmButtonClass(request.variant)}"
					onclick={() => close(true)}
				>
					{request.confirmText}
				</button>
			</div>
		</div>
	</div>
{/if}
