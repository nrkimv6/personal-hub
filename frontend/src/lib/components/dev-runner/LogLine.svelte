<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { LogLineStyle, ParsedLine } from '$lib/dev-runner/log-types';
	import type { LogLineVariant } from '$lib/dev-runner/log-line-variant';

	interface Props {
		line: ParsedLine;
		style: LogLineStyle;
		variant: LogLineVariant;
		containerClass: string;
		bodyClass: string;
		expanded: boolean;
		collapsed: boolean;
		expandLabel: string;
		timestampClass?: string;
		badgeWrapperClass?: string;
		title?: string;
		onToggleExpand: () => void;
		onExpandKeydown: (event: KeyboardEvent) => void;
		expandButtonClass: string;
		children: Snippet;
	}

	let {
		line,
		style,
		variant,
		containerClass,
		bodyClass,
		expanded,
		collapsed,
		expandLabel,
		timestampClass = 'text-xs text-gray-400/60 shrink-0 w-[56px] tabular-nums select-none',
		badgeWrapperClass = '',
		title,
		onToggleExpand,
		onExpandKeydown,
		expandButtonClass,
		children
	}: Props = $props();
</script>

<div class={containerClass} {title}>
	{#if variant !== 'cycle'}
		<span class={timestampClass}>{line.timestamp}</span>
	{/if}
	<span class="shrink-0 w-[42px] text-right {style.text} {badgeWrapperClass}">
		<span class="dr-tag-badge {style.bg}">{line.tag}</span>
	</span>
	<span class={bodyClass}>
		{@render children()}
	</span>
	{#if collapsed}
		<button
			type="button"
			class={expandButtonClass}
			aria-expanded={expanded}
			aria-pressed={expanded}
			onclick={onToggleExpand}
			onkeydown={onExpandKeydown}
		>
			{expanded ? '접기' : expandLabel}
		</button>
	{/if}
</div>
