<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { confirmState, resolveConfirm, type ConfirmRequest } from '$lib/stores/confirm';

	let request = $state<ConfirmRequest | null>(null);

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

	onMount(() => {
		window.addEventListener('keydown', handleKeydown);
	});

	onDestroy(() => {
		window.removeEventListener('keydown', handleKeydown);
		unsubscribe();
	});
</script>

{#if request}
	<div class="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 px-4">
		<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
		<div class="absolute inset-0" onclick={() => close(false)}></div>
		<section
			class="relative w-full max-w-md rounded-lg border border-border bg-card p-5 text-card-foreground shadow-xl"
			role="dialog"
			aria-modal="true"
			aria-labelledby="confirm-modal-title"
			aria-describedby="confirm-modal-message"
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
					class="rounded-md px-3 py-1.5 text-sm font-medium text-white transition-colors {request.variant === 'danger' ? 'bg-destructive hover:bg-destructive/90' : 'bg-primary hover:bg-primary-hover'}"
					onclick={() => close(true)}
				>
					{request.confirmText}
				</button>
			</div>
		</section>
	</div>
{/if}
