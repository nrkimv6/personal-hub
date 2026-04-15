export interface ViewPoint {
  x: number;
  y: number;
}

export interface PanBounds {
  viewportWidth: number;
  viewportHeight: number;
  contentWidth: number;
  contentHeight: number;
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export function toViewPoint(xNorm: number, yNorm: number, width: number, height: number): ViewPoint {
  return {
    x: width * clamp01(xNorm),
    y: height * clamp01(yNorm)
  };
}

export function toNormalizedPoint(xPx: number, yPx: number, width: number, height: number) {
  const safeWidth = width || 1;
  const safeHeight = height || 1;

  return {
    xNorm: clamp01(xPx / safeWidth),
    yNorm: clamp01(yPx / safeHeight)
  };
}

export function computePinchScale(previousDistance: number, nextDistance: number): number {
  if (previousDistance <= 0 || nextDistance <= 0) {
    return 1;
  }

  return nextDistance / previousDistance;
}

export function clampZoom(zoom: number, minZoom: number, maxZoom: number): number {
  return Math.max(minZoom, Math.min(maxZoom, zoom));
}

export function clampPan(panX: number, panY: number, bounds: PanBounds) {
  const minX = Math.min(0, bounds.viewportWidth - bounds.contentWidth);
  const minY = Math.min(0, bounds.viewportHeight - bounds.contentHeight);

  return {
    panX: Math.min(0, Math.max(minX, panX)),
    panY: Math.min(0, Math.max(minY, panY))
  };
}
