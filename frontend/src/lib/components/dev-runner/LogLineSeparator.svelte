<script lang="ts">
	interface Props {
		text: string;
	}

	let { text }: Props = $props();
</script>

<div class="py-2 text-center select-none opacity-60">
	<span class="text-gray-500 text-[10px]">{text}</span><!-- separator -->
</div>
