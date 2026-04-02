<script lang="ts">
  import { afterUpdate, onDestroy } from 'svelte';

  export let visible = false;
  export let pointerX = 0;
  export let pointerY = 0;
  export let sourceX = 0;
  export let sourceY = 0;
  export let sourceCanvas: HTMLCanvasElement | null = null;
  export let containerWidth = 1;
  export let containerHeight = 1;
  export let diameter = 136;
  export let zoom = 3.5;
  export let offset = 16;

  const boundaryPadding = 6;
  let canvasEl: HTMLCanvasElement | null = null;
  let frameId: number | null = null;
  let left = 0;
  let top = 0;

  function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
  }

  function queueDraw() {
    if (!visible || !sourceCanvas || !canvasEl || frameId !== null) return;
    frameId = requestAnimationFrame(() => {
      frameId = null;
      draw();
    });
  }

  function cancelDraw() {
    if (frameId === null) return;
    cancelAnimationFrame(frameId);
    frameId = null;
  }

  function draw() {
    if (!visible || !sourceCanvas || !canvasEl) return;

    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;

    const width = sourceCanvas.width;
    const height = sourceCanvas.height;
    if (!width || !height) return;

    const radius = diameter / 2;
    const sampleWidth = Math.max(8, diameter / zoom);
    const sampleHeight = Math.max(8, diameter / zoom);
    const sx = clamp(sourceX - sampleWidth / 2, 0, Math.max(0, width - sampleWidth));
    const sy = clamp(sourceY - sampleHeight / 2, 0, Math.max(0, height - sampleHeight));

    ctx.clearRect(0, 0, diameter, diameter);
    ctx.save();
    ctx.beginPath();
    ctx.arc(radius, radius, radius - 2, 0, Math.PI * 2);
    ctx.clip();
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(sourceCanvas, sx, sy, sampleWidth, sampleHeight, 0, 0, diameter, diameter);
    ctx.restore();

    ctx.strokeStyle = 'rgba(255,255,255,0.9)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(radius, radius, radius - 2, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = 'rgba(0,0,0,0.45)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(radius, 0);
    ctx.lineTo(radius, diameter);
    ctx.moveTo(0, radius);
    ctx.lineTo(diameter, radius);
    ctx.stroke();
  }

  $: {
    const radius = diameter / 2;
    const minX = radius + boundaryPadding;
    const maxX = Math.max(minX, containerWidth - radius - boundaryPadding);
    const centerX = clamp(pointerX, minX, maxX);

    const minY = radius + boundaryPadding;
    const maxY = Math.max(minY, containerHeight - radius - boundaryPadding);
    const preferredY =
      pointerY - radius - offset >= minY ? pointerY - radius - offset : pointerY + radius + offset;
    const centerY = clamp(preferredY, minY, maxY);

    left = centerX - radius;
    top = centerY - radius;
  }

  afterUpdate(() => {
    if (visible) queueDraw();
    else cancelDraw();
  });

  onDestroy(cancelDraw);
</script>

{#if visible}
  <div
    class="pointer-events-none absolute z-20"
    style={`left:${left}px;top:${top}px;width:${diameter}px;height:${diameter}px;`}
  >
    <canvas
      bind:this={canvasEl}
      width={diameter}
      height={diameter}
      class="h-full w-full rounded-full ring-2 ring-black/35 shadow-xl"
    />
  </div>
{/if}
