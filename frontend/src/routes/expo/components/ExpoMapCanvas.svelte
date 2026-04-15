<script lang="ts">
  import type { ExpoBooth, ExpoMapDocument } from '$lib/types';
  import {
    clampPan,
    clampZoom,
    computePinchScale,
    toViewPoint
  } from '../utils/mapTransform';

  interface Props {
    map: ExpoMapDocument['map'];
    booths: ExpoBooth[];
    matchedBoothIds: Set<string>;
    selectedBoothId: string | null;
    onImageError: () => void;
    onSelectBooth: (boothId: string) => void;
  }

  interface PointerPoint {
    clientX: number;
    clientY: number;
  }

  let {
    map,
    booths,
    matchedBoothIds,
    selectedBoothId,
    onImageError,
    onSelectBooth
  }: Props = $props();

  const minZoom = 1;
  const maxZoom = 4;
  const tapMoveThreshold = 8;
  const tapSelectionRadius = 28;
  const doubleTapResetDelayMs = 280;
  const activePointers = new Map<number, PointerPoint>();
  const pointerStartPoints = new Map<number, PointerPoint>();

  let containerEl: HTMLDivElement | null = null;
  let zoom = $state(1);
  let panX = $state(0);
  let panY = $state(0);
  let draggingPointerId = $state<number | null>(null);
  let lastDragPoint = $state<PointerPoint | null>(null);
  let pinchDistance = $state<number | null>(null);
  let pinchMidpoint = $state<{ x: number; y: number } | null>(null);
  let focusedBoothId = $state<string | null>(null);
  let lastTouchTapAt = $state(0);
  let lastTouchTapPoint = $state<PointerPoint | null>(null);

  function getViewport() {
    const rect = containerEl?.getBoundingClientRect();
    return {
      width: rect?.width || 1,
      height: rect?.height || 1
    };
  }

  function applyTransform(nextZoom: number, nextPanX: number, nextPanY: number) {
    const viewport = getViewport();
    const clampedZoom = clampZoom(nextZoom, minZoom, maxZoom);
    const clampedPan = clampPan(nextPanX, nextPanY, {
      viewportWidth: viewport.width,
      viewportHeight: viewport.height,
      contentWidth: viewport.width * clampedZoom,
      contentHeight: viewport.height * clampedZoom
    });

    zoom = clampedZoom;
    panX = clampedPan.panX;
    panY = clampedPan.panY;
  }

  function zoomAtViewportPoint(viewX: number, viewY: number, nextZoom: number, basePanX = panX, basePanY = panY) {
    const contentX = (viewX - basePanX) / zoom;
    const contentY = (viewY - basePanY) / zoom;
    const nextPanX = viewX - contentX * nextZoom;
    const nextPanY = viewY - contentY * nextZoom;

    applyTransform(nextZoom, nextPanX, nextPanY);
  }

  function zoomAtClientPoint(clientX: number, clientY: number, nextZoom: number) {
    const rect = containerEl?.getBoundingClientRect();
    if (!rect) {
      return;
    }

    zoomAtViewportPoint(clientX - rect.left, clientY - rect.top, nextZoom);
  }

  function getDistance(points: PointerPoint[]) {
    return Math.hypot(points[0].clientX - points[1].clientX, points[0].clientY - points[1].clientY);
  }

  function getMidpoint(points: PointerPoint[]) {
    return {
      x: (points[0].clientX + points[1].clientX) / 2,
      y: (points[0].clientY + points[1].clientY) / 2
    };
  }

  function resetGestureState() {
    draggingPointerId = null;
    lastDragPoint = null;
    pinchDistance = null;
    pinchMidpoint = null;
  }

  function resetView() {
    applyTransform(1, 0, 0);
  }

  function findNearestBoothAtViewportPoint(viewX: number, viewY: number) {
    const viewport = getViewport();
    let nearestBooth: ExpoBooth | null = null;
    let nearestDistance = Number.POSITIVE_INFINITY;

    for (const booth of booths) {
      const point = toViewPoint(booth.pin.xNorm, booth.pin.yNorm, viewport.width, viewport.height);
      const mappedX = point.x * zoom + panX;
      const mappedY = point.y * zoom + panY;
      const distance = Math.hypot(mappedX - viewX, mappedY - viewY);

      if (distance < nearestDistance) {
        nearestBooth = booth;
        nearestDistance = distance;
      }
    }

    if (!nearestBooth || nearestDistance > tapSelectionRadius) {
      return null;
    }

    return nearestBooth;
  }

  function focusBooth(boothId: string | null) {
    if (!boothId || !containerEl) {
      return;
    }

    const booth = booths.find((item) => item.id === boothId);
    if (!booth) {
      return;
    }

    const viewport = getViewport();
    const point = toViewPoint(booth.pin.xNorm, booth.pin.yNorm, viewport.width, viewport.height);
    const nextZoom = Math.max(zoom, 1.8);

    applyTransform(
      nextZoom,
      viewport.width / 2 - point.x * nextZoom,
      viewport.height / 2 - point.y * nextZoom
    );
  }

  function handleWheel(event: WheelEvent) {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
    zoomAtClientPoint(event.clientX, event.clientY, zoom * factor);
  }

  function handlePointerDown(event: PointerEvent) {
    if (event.target instanceof HTMLButtonElement) {
      return;
    }

    event.preventDefault();
    activePointers.set(event.pointerId, { clientX: event.clientX, clientY: event.clientY });
    pointerStartPoints.set(event.pointerId, { clientX: event.clientX, clientY: event.clientY });
    (event.currentTarget as HTMLDivElement).setPointerCapture(event.pointerId);

    if (activePointers.size === 1) {
      draggingPointerId = event.pointerId;
      lastDragPoint = { clientX: event.clientX, clientY: event.clientY };
    } else if (activePointers.size === 2) {
      const points = [...activePointers.values()];
      pinchDistance = getDistance(points);
      pinchMidpoint = getMidpoint(points);
      draggingPointerId = null;
      lastDragPoint = null;
    }
  }

  function handlePointerMove(event: PointerEvent) {
    if (!activePointers.has(event.pointerId)) {
      return;
    }

    event.preventDefault();
    activePointers.set(event.pointerId, { clientX: event.clientX, clientY: event.clientY });

    if (activePointers.size === 2 && pinchDistance && pinchMidpoint) {
      const points = [...activePointers.values()];
      const nextDistance = getDistance(points);
      const nextMidpoint = getMidpoint(points);
      const rect = containerEl?.getBoundingClientRect();

      if (!rect) {
        return;
      }

      const translatedPanX = panX + (nextMidpoint.x - pinchMidpoint.x);
      const translatedPanY = panY + (nextMidpoint.y - pinchMidpoint.y);
      const nextZoom = clampZoom(zoom * computePinchScale(pinchDistance, nextDistance), minZoom, maxZoom);

      zoomAtViewportPoint(
        nextMidpoint.x - rect.left,
        nextMidpoint.y - rect.top,
        nextZoom,
        translatedPanX,
        translatedPanY
      );

      pinchDistance = nextDistance;
      pinchMidpoint = nextMidpoint;
      return;
    }

    if (draggingPointerId !== event.pointerId || !lastDragPoint) {
      return;
    }

    applyTransform(
      zoom,
      panX + (event.clientX - lastDragPoint.clientX),
      panY + (event.clientY - lastDragPoint.clientY)
    );

    lastDragPoint = { clientX: event.clientX, clientY: event.clientY };
  }

  function handlePointerUp(event: PointerEvent) {
    if (!activePointers.has(event.pointerId)) {
      return;
    }

    const wasSinglePointer = activePointers.size === 1;
    const startPoint = pointerStartPoints.get(event.pointerId);
    activePointers.delete(event.pointerId);
    pointerStartPoints.delete(event.pointerId);

    if (wasSinglePointer && startPoint) {
      const travelDistance = Math.hypot(
        event.clientX - startPoint.clientX,
        event.clientY - startPoint.clientY
      );

      if (travelDistance <= tapMoveThreshold) {
        const rect = containerEl?.getBoundingClientRect();
        if (rect) {
          const tapPoint = {
            clientX: event.clientX,
            clientY: event.clientY
          };

          if (event.pointerType === 'touch' && lastTouchTapPoint) {
            const tapInterval = event.timeStamp - lastTouchTapAt;
            const tapDistance = Math.hypot(
              tapPoint.clientX - lastTouchTapPoint.clientX,
              tapPoint.clientY - lastTouchTapPoint.clientY
            );

            if (tapInterval <= doubleTapResetDelayMs && tapDistance <= tapSelectionRadius) {
              lastTouchTapAt = 0;
              lastTouchTapPoint = null;
              resetView();
              resetGestureState();
              return;
            }
          }

          const nearestBooth = findNearestBoothAtViewportPoint(
            event.clientX - rect.left,
            event.clientY - rect.top
          );

          if (nearestBooth) {
            onSelectBooth(nearestBooth.id);
          }

          if (event.pointerType === 'touch') {
            lastTouchTapAt = event.timeStamp;
            lastTouchTapPoint = tapPoint;
          }
        }
      }
    }

    if (activePointers.size === 1) {
      const [pointerId, point] = [...activePointers.entries()][0];
      draggingPointerId = pointerId;
      lastDragPoint = point;
      pinchDistance = null;
      pinchMidpoint = null;
      return;
    }

    if (activePointers.size === 0) {
      resetGestureState();
    }
  }

  $effect(() => {
    if (selectedBoothId && selectedBoothId !== focusedBoothId) {
      focusedBoothId = selectedBoothId;
      focusBooth(selectedBoothId);
    }
  });
</script>

<div
  bind:this={containerEl}
  class="relative overflow-hidden rounded-[32px] border border-slate-200 bg-[radial-gradient(circle_at_top,_rgba(251,191,36,0.18),_transparent_32%),linear-gradient(180deg,_#fffdf7_0%,_#f6f1e7_100%)] shadow-[0_24px_60px_rgba(148,163,184,0.18)]"
  role="application"
  aria-label="커피엑스포 2026 부스맵"
  style={`aspect-ratio: ${map.width} / ${map.height}; touch-action: none; overscroll-behavior: contain;`}
  onwheel={handleWheel}
  onpointerdown={handlePointerDown}
  onpointermove={handlePointerMove}
  onpointerup={handlePointerUp}
  onpointercancel={handlePointerUp}
  onpointerleave={handlePointerUp}
  ondblclick={resetView}
>
  <div
    class="absolute inset-0 origin-top-left"
    style={`transform: translate(${panX}px, ${panY}px) scale(${zoom});`}
  >
    <img
      src={map.imageSrc}
      alt={map.alt}
      class="pointer-events-none absolute inset-0 h-full w-full select-none object-contain"
      decoding="async"
      draggable="false"
      loading="eager"
      onerror={onImageError}
    />

    {#each booths as booth}
      {@const isSelected = booth.id === selectedBoothId}
      {@const isMatched = matchedBoothIds.has(booth.id)}
      <button
        type="button"
        aria-label={`${booth.id} ${booth.name}`}
        class="absolute flex min-h-11 min-w-11 items-center justify-center rounded-full border text-[10px] font-bold uppercase shadow transition focus:outline-none focus:ring-4 focus:ring-amber-300"
        class:border-amber-500={isSelected}
        class:bg-amber-400={isSelected}
        class:text-slate-950={isSelected}
        class:border-slate-200={!isSelected}
        class:bg-slate-900={!isSelected}
        class:text-white={!isSelected}
        class:opacity-30={!isMatched}
        class:opacity-100={isMatched}
        style={`left: ${booth.pin.xNorm * 100}%; top: ${booth.pin.yNorm * 100}%; transform: translate(-50%, -50%) scale(${1 / zoom});`}
        onclick={(event) => {
          event.stopPropagation();
          onSelectBooth(booth.id);
        }}
      >
        {booth.id}
      </button>
    {/each}
  </div>

  <div class="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between px-4 pb-4 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500">
    <span>Pinch / Wheel</span>
    <span>Double Tap Reset</span>
  </div>
</div>
