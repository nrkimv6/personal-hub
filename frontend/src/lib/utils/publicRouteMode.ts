export type PublicRouteMode = 'public' | 'admin';
export type PublicLandingPath = '/events' | '/monitoring';

type RouteModeContext = {
  fetch?: typeof fetch;
  url?: URL;
};

type HostRouteContext = {
  hostname?: string;
  port?: string;
  url?: URL;
};

export type ExpoRouteContract = {
  isPublicPreview: boolean;
  isLocalAdminDev: boolean;
  canOpenExpoAdminWorkspace: boolean;
  shouldRedirectExpoAuthor: boolean;
};

type ExpoRouteContractContext = HostRouteContext & {
  mode?: PublicRouteMode | null;
  isAdmin?: boolean;
};

function resolveHostRouteMode(context: HostRouteContext): PublicRouteMode | null {
  const hostname = context.url?.hostname ?? context.hostname;
  const port = context.url?.port ?? context.port ?? '';

  if (!hostname) {
    return null;
  }

  const normalizedHostname = hostname.toLowerCase();
  const isLocalhost =
    normalizedHostname === 'localhost' ||
    normalizedHostname === '127.0.0.1' ||
    normalizedHostname === '127.0.0.2' ||
    normalizedHostname === '::1';

  if (!isLocalhost) {
    return null;
  }

  if (port === '6100') {
    return 'public';
  }

  return 'admin';
}

export function getLocalhostRouteModeFallback(hostname: string, port: string): PublicRouteMode | null {
  return resolveHostRouteMode({ hostname, port });
}

function getRouteModeFallback(url?: URL): PublicRouteMode {
  const fallbackFromUrl = resolveHostRouteMode({ url });
  if (fallbackFromUrl) {
    return fallbackFromUrl;
  }

  if (typeof window !== 'undefined') {
    const fallbackFromWindow = resolveHostRouteMode({
      hostname: window.location.hostname,
      port: window.location.port
    });
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
  // Admin mode lands on the unified monitoring workspace; public preview stays on the events landing.
  return mode === 'admin' ? '/monitoring' : '/events';
}

export async function resolvePublicLandingPath(context: RouteModeContext = {}): Promise<PublicLandingPath> {
  return getLandingPathForMode(await resolvePublicRouteMode(context));
}

export function getExpoRouteContract(context: ExpoRouteContractContext = {}): ExpoRouteContract {
  const hostRouteMode = resolveHostRouteMode(context);
  const isPublicPreview = hostRouteMode === 'public' || context.mode === 'public';
  const isLocalAdminDev = hostRouteMode === 'admin';
  const isAdminMode = hostRouteMode === 'admin' || context.mode === 'admin';
  const canOpenExpoAdminWorkspace =
    !isPublicPreview && (context.isAdmin === true || isAdminMode);

  return {
    isPublicPreview,
    isLocalAdminDev,
    canOpenExpoAdminWorkspace,
    shouldRedirectExpoAuthor: isPublicPreview
  };
}
