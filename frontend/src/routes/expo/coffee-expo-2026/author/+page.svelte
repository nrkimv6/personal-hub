<script lang="ts">
  import { browser } from '$app/environment';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import { toast } from '$lib/stores/toast';
  import type { ExpoDraftBooth, ExpoMapDocument } from '$lib/types';
  import ExpoAdminWorkspace from '../../components/ExpoAdminWorkspace.svelte';
  import { serializeExpoDraftsForExport } from '../../utils/authorDraft';
  import expoData from '../expo-data.json';

  const expo = expoData as ExpoMapDocument;

  async function handleSaveDrafts(drafts: ExpoDraftBooth[]) {
    if (!browser || drafts.length === 0) {
      toast.warning('복사할 좌표 draft가 없습니다.');
      return;
    }

    try {
      await navigator.clipboard.writeText(serializeExpoDraftsForExport(drafts));
      toast.success(`${drafts.length}개 draft를 복사했습니다.`);
    } catch {
      toast.error('클립보드 복사에 실패했습니다.');
    }
  }
</script>

<svelte:head>
  <title>{expo.title} Author Helper</title>
  <meta name="robots" content="noindex" />
</svelte:head>

<main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-6 bg-[linear-gradient(180deg,_#fffaf2_0%,_#f6f1e8_100%)] px-4 py-6 lg:px-6">
  <PageHeader title={`${expo.title} 좌표 작성`} subtitle="admin 모드 전용 author helper" />
  <ExpoAdminWorkspace
    existingBooths={expo.booths}
    map={expo.map}
    onSaveDrafts={handleSaveDrafts}
    previewHref="/expo/coffee-expo-2026"
    saveButtonLabel="JSON 복사"
    slug={expo.slug}
    title={expo.title}
  />
</main>
