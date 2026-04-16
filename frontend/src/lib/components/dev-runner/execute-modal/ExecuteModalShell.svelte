<script lang="ts">
	interface Props {
		open: boolean;
		onClose: () => void;
		titleId?: string;
	}

	let { open, onClose, titleId = 'execute-modal-title' }: Props = $props();
	let previousOverflow = '';

	$effect(() => {
		if (!open) return;

		previousOverflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';

		const handleKeydown = (event: KeyboardEvent) => {
			if (event.key === 'Escape') {
				onClose();
			}
		};

		window.addEventListener('keydown', handleKeydown);

		return () => {
			window.removeEventListener('keydown', handleKeydown);
			document.body.style.overflow = previousOverflow;
		};
	});
</script>

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 max-sm:px-0"
		onclick={onClose}
		role="presentation"
	>
		<div
			class="bg-card text-foreground rounded-xl shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] flex flex-col overflow-hidden max-sm:mx-0 max-sm:h-full max-sm:max-h-full max-sm:rounded-none max-sm:w-full"
			role="dialog"
			aria-modal="true"
			aria-labelledby={titleId}
			onclick={(event) => event.stopPropagation()}
		>
			<slot name="header" />

			<slot name="banner" />

			<div class="flex-1 min-h-0 overflow-y-auto">
				<slot />
			</div>

			<slot name="actions" />
		</div>
	</div>
{/if}
