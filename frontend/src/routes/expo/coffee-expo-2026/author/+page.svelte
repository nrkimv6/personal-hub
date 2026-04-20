<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import type { ExpoMapDocument } from '$lib/types';
  import ExpoAdminWorkspace from '../../components/ExpoAdminWorkspace.svelte';
  import expoData from '../expo-data.json';

  const expo = expoData as ExpoMapDocument;

  onMount(() => {
    const isLocalhost =
      window.location.hostname === 'localhost' ||
      window.location.hostname === '127.0.0.1' ||
      window.location.hostname === '127.0.0.2' ||
      window.location.hostname === '::1';

    if (isLocalhost && window.location.port === '6100') {
      goto('/expo/coffee-expo-2026', { replaceState: true, keepFocus: true, noScroll: true });
    }
  });
</script>

<svelte:head>
  <title>{expo.title} Author Helper</title>
  <meta name="robots" content="noindex" />
</svelte:head>

<main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-6 bg-[linear-gradient(180deg,_#fffaf2_0%,_#f6f1e8_100%)] px-4 py-6 lg:px-6">
  <PageHeader title={`${expo.title} 좌표 작성`} subtitle="내부 제작/보정 전용 author helper" />
  <ExpoAdminWorkspace
    existingBooths={expo.booths}
    map={expo.map}
    previewHref="/expo/coffee-expo-2026"
    saveButtonLabel="Export JSON"
    slug={expo.slug}
    title={expo.title}
  />
</main>
