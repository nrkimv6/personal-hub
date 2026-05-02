<script lang="ts">
  import PublicCoupangHistoryTab from '$lib/components/coupang/PublicCoupangHistoryTab.svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
</script>

<div class="p-4 lg:p-6">
  <PageHeader title="쿠팡 취소표 이력 (Legacy)" density="compact" />
  <PublicCoupangHistoryTab />
</div>
