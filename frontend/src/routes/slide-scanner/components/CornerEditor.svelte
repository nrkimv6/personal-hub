<script lang="ts">
  import { createEventDispatcher, onDestroy } from 'svelte';

  import type { SlidePoint } from '$lib/api/slide-scanner';

  import Loupe from './Loupe.svelte';

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
  let sourceCanvas: HTMLCanvasElement | null = null;
  let loupeVisible = false;
  let loupePointerX = 0;
  let loupePointerY = 0;
  let loupeSourceX = 0;
  let loupeSourceY = 0;
  let pointerMoveFrameId: number | null = null;
  let pendingPointerEvent: PointerEvent | null = null;

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

  $: if (!imageUrl) {
    sourceCanvas = null;
    loupeVisible = false;
  }

  function updateImageMetrics() {
    if (!imageEl) return;
    naturalWidth = imageEl.naturalWidth || 1;
    naturalHeight = imageEl.naturalHeight || 1;
    displayWidth = imageEl.clientWidth || 1;
    displayHeight = imageEl.clientHeight || 1;
    primeSourceCanvas();
  }

  function primeSourceCanvas() {
    if (!imageEl) return;
    const width = imageEl.naturalWidth || 0;
    const height = imageEl.naturalHeight || 0;
    if (!width || !height) {
      sourceCanvas = null;
      return;
    }

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      sourceCanvas = null;
      return;
    }

    ctx.drawImage(imageEl, 0, 0, width, height);
    sourceCanvas = canvas;
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
    const width = rect.width || 1;
    const height = rect.height || 1;
    const dx = clamp(event.clientX - rect.left, 0, width);
    const dy = clamp(event.clientY - rect.top, 0, height);
    return {
      x: (dx / width) * naturalWidth,
      y: (dy / height) * naturalHeight
    };
  }

  function updateLoupeState(event: PointerEvent, point: SlidePoint) {
    if (!svgEl) return;
    const rect = svgEl.getBoundingClientRect();
    loupePointerX = clamp(event.clientX - rect.left, 0, rect.width || 1);
    loupePointerY = clamp(event.clientY - rect.top, 0, rect.height || 1);
    loupeSourceX = point.x;
    loupeSourceY = point.y;
  }

  function handlePointerDown(index: number, event: PointerEvent) {
    if (disabled) return;
    activeIndex = index;
    dragging = true;
    loupeVisible = true;
    const initialPoint = localPoints[index] ?? toImageCoordinate(event);
    updateLoupeState(event, initialPoint);
    (event.currentTarget as SVGCircleElement | null)?.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function flushPointerMove() {
    pointerMoveFrameId = null;
    const nextEvent = pendingPointerEvent;
    pendingPointerEvent = null;
    if (!nextEvent || activeIndex === null || disabled) return;

    const next = toImageCoordinate(nextEvent);
    localPoints[activeIndex] = next;
    localPoints = [...localPoints];
    updateLoupeState(nextEvent, next);
    dispatch('change', { points: localPoints });
  }

  function handlePointerMove(event: PointerEvent) {
    if (activeIndex === null || disabled) return;
    pendingPointerEvent = event;
    if (pointerMoveFrameId !== null) return;
    pointerMoveFrameId = requestAnimationFrame(flushPointerMove);
  }

  function clearPointerFrame() {
    if (pointerMoveFrameId !== null) {
      cancelAnimationFrame(pointerMoveFrameId);
      pointerMoveFrameId = null;
    }
    pendingPointerEvent = null;
  }

  function handlePointerUp() {
    activeIndex = null;
    dragging = false;
    loupeVisible = false;
    clearPointerFrame();
  }

  onDestroy(clearPointerFrame);

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
          onlostpointercapture={handlePointerUp}
        />
      {/each}
    </svg>
    <Loupe
      visible={loupeVisible && !disabled && Boolean(sourceCanvas)}
      pointerX={loupePointerX}
      pointerY={loupePointerY}
      sourceX={loupeSourceX}
      sourceY={loupeSourceY}
      {sourceCanvas}
      containerWidth={displayWidth}
      containerHeight={displayHeight}
    />
  </div>
</div>
