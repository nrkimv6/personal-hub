<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { SlidePoint } from '$lib/api/slide-scanner';

  export let imageUrl = '';
  export let points: SlidePoint[] = [];
  export let disabled = false;

  const dispatch = createEventDispatcher<{ change: { points: SlidePoint[] } }>();

  let imageEl: HTMLImageElement | null = null;
  let svgEl: SVGSVGElement | null = null;
  let activeIndex: number | null = null;
  let dragging = false;
  let naturalWidth = 1;
  let naturalHeight = 1;
  let displayWidth = 1;
  let displayHeight = 1;
  let localPoints: SlidePoint[] = [];
  let polygonPath = '';

  $: if (!dragging) {
    localPoints =
      points.length === 4
        ? points.map((point) => ({ x: point.x, y: point.y }))
        : [
            { x: 0, y: 0 },
            { x: naturalWidth, y: 0 },
            { x: naturalWidth, y: naturalHeight },
            { x: 0, y: naturalHeight }
          ];
  }

  function updateImageMetrics() {
    if (!imageEl) return;
    naturalWidth = imageEl.naturalWidth || 1;
    naturalHeight = imageEl.naturalHeight || 1;
    displayWidth = imageEl.clientWidth || 1;
    displayHeight = imageEl.clientHeight || 1;
  }

  function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
  }

  function toDisplay(point: SlidePoint): SlidePoint {
    return {
      x: (point.x / naturalWidth) * displayWidth,
      y: (point.y / naturalHeight) * displayHeight
    };
  }

  function toImageCoordinate(event: PointerEvent): SlidePoint {
    if (!svgEl) return { x: 0, y: 0 };
    const rect = svgEl.getBoundingClientRect();
    const dx = clamp(event.clientX - rect.left, 0, rect.width);
    const dy = clamp(event.clientY - rect.top, 0, rect.height);
    return {
      x: (dx / rect.width) * naturalWidth,
      y: (dy / rect.height) * naturalHeight
    };
  }

  function handlePointerDown(index: number, event: PointerEvent) {
    if (disabled) return;
    activeIndex = index;
    dragging = true;
    (event.currentTarget as SVGCircleElement).setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function handlePointerMove(event: PointerEvent) {
    if (activeIndex === null || disabled) return;
    const next = toImageCoordinate(event);
    localPoints[activeIndex] = next;
    localPoints = [...localPoints];
    dispatch('change', { points: localPoints });
  }

  function handlePointerUp() {
    activeIndex = null;
    dragging = false;
  }

  $: polygonPath = localPoints
    .map((point) => {
      const displayPoint = toDisplay(point);
      return `${displayPoint.x},${displayPoint.y}`;
    })
    .join(' ');
</script>

<div class="rounded-xl border border-border bg-card p-3">
  <div class="relative mx-auto inline-block w-full">
    <img
      bind:this={imageEl}
      src={imageUrl}
      alt="slide"
      class="mx-auto max-h-[70vh] w-auto max-w-full rounded-md"
      onload={updateImageMetrics}
    />
    <svg
      bind:this={svgEl}
      class="pointer-events-auto absolute left-1/2 top-0 -translate-x-1/2"
      width={displayWidth}
      height={displayHeight}
      onpointermove={handlePointerMove}
      onpointerup={handlePointerUp}
      onpointercancel={handlePointerUp}
    >
      <polygon points={polygonPath} fill="rgba(59,130,246,0.18)" stroke="#3b82f6" stroke-width="2" />
      {#each localPoints as point, index}
        {@const displayPoint = toDisplay(point)}
        <circle
          cx={displayPoint.x}
          cy={displayPoint.y}
          r="7"
          fill={activeIndex === index ? '#1d4ed8' : '#2563eb'}
          class="cursor-move"
          onpointerdown={(event) => handlePointerDown(index, event)}
        />
      {/each}
    </svg>
  </div>
</div>
