<script lang="ts">
  export let resultUrl: string | null = null;
</script>

{#if resultUrl}
  <section class="rounded-xl border border-border bg-card p-4">
    <div class="mb-3 flex items-center justify-between">
      <h3 class="text-sm font-semibold">보정 결과</h3>
      <a href={resultUrl} download class="btn btn-sm btn-outline">다운로드</a>
    </div>
    <img src={resultUrl} alt="result" class="max-h-[60vh] w-full rounded-md object-contain" />
  </section>
{/if}
