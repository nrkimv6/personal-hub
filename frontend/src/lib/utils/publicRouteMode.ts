export type PublicRouteMode = 'public' | 'admin';
export type PublicLandingPath = '/events' | '/monitoring';

export async function resolvePublicRouteMode(): Promise<PublicRouteMode> {
  try {
    const response = await fetch('/api/v1/system/mode', {
      headers: {
        Accept: 'application/json'
      }
    });

    if (!response.ok) {
      return 'public';
    }

    const payload: { mode?: unknown } = await response.json();
    return payload.mode === 'admin' ? 'admin' : 'public';
  } catch {
    return 'public';
  }
}

export function getLandingPathForMode(mode: PublicRouteMode): PublicLandingPath {
  return mode === 'admin' ? '/monitoring' : '/events';
}

export async function resolvePublicLandingPath(): Promise<PublicLandingPath> {
  return getLandingPathForMode(await resolvePublicRouteMode());
}
