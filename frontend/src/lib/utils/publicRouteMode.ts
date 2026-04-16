export type PublicRouteMode = 'public' | 'admin';
export type PublicLandingPath = '/events' | '/monitoring';

type RouteModeContext = {
  fetch?: typeof fetch;
  url?: URL;
};

export function getLocalhostRouteModeFallback(hostname: string, port: string): PublicRouteMode | null {
  const normalizedHostname = hostname.toLowerCase();
  const isLocalhost =
    normalizedHostname === 'localhost' ||
    normalizedHostname === '127.0.0.1' ||
    normalizedHostname === '::1';

  if (!isLocalhost) {
    return null;
  }

  if (port === '6100') {
    return 'public';
  }

  return 'admin';
}

function getRouteModeFallback(url?: URL): PublicRouteMode {
  const fallbackFromUrl = url ? getLocalhostRouteModeFallback(url.hostname, url.port) : null;
  if (fallbackFromUrl) {
    return fallbackFromUrl;
  }

  if (typeof window !== 'undefined') {
    const fallbackFromWindow = getLocalhostRouteModeFallback(window.location.hostname, window.location.port);
    if (fallbackFromWindow) {
      return fallbackFromWindow;
    }
  }

  return 'public';
}

export async function resolvePublicRouteMode(context: RouteModeContext = {}): Promise<PublicRouteMode> {
  const fetchImpl = context.fetch ?? fetch;
  try {
    const response = await fetchImpl('/api/v1/system/mode', {
      headers: {
        Accept: 'application/json'
      }
    });

    if (!response.ok) {
      return getRouteModeFallback(context.url);
    }

    const payload: { mode?: unknown } = await response.json();
    if (payload.mode === 'admin' || payload.mode === 'public') {
      return payload.mode;
    }

    return getRouteModeFallback(context.url);
  } catch {
    return getRouteModeFallback(context.url);
  }
}

export function getLandingPathForMode(mode: PublicRouteMode): PublicLandingPath {
  return mode === 'admin' ? '/monitoring' : '/events';
}

export async function resolvePublicLandingPath(context: RouteModeContext = {}): Promise<PublicLandingPath> {
  return getLandingPathForMode(await resolvePublicRouteMode(context));
}
