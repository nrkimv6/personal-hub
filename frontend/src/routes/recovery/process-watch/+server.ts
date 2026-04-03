import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { assertAdminCredential, assertLocalRequest } from '$lib/server/recovery-guard';
import { readLocalProcessWatchLatest } from '$lib/server/process-watch-fallback';

const FASTAPI_BASE = 'http://localhost:8001/api/v1/system/process-watch/latest';

function buildForwardHeaders(req: Request): HeadersInit {
  const headers: HeadersInit = {};
  const auth = req.headers.get('authorization');
  const cookie = req.headers.get('cookie');
  if (auth) headers['authorization'] = auth;
  if (cookie) headers['cookie'] = cookie;
  return headers;
}

export const GET: RequestHandler = async (event) => {
  assertLocalRequest(event);
  assertAdminCredential(event);

  const minMb = Number(event.url.searchParams.get('min_mb') ?? '0');
  const limit = Number(event.url.searchParams.get('limit') ?? '50');
  const scope = event.url.searchParams.get('scope') ?? undefined;

  const safeMinMb = Number.isFinite(minMb) ? Math.max(0, minMb) : 0;
  const safeLimit = Number.isFinite(limit) ? Math.max(1, Math.min(500, limit)) : 50;

  let fastApiError: string | null = null;
  const params = new URLSearchParams();
  params.set('min_mb', String(safeMinMb));
  params.set('limit', String(safeLimit));
  if (scope) params.set('scope', scope);

  try {
    const response = await fetch(`${FASTAPI_BASE}?${params.toString()}`, {
      method: 'GET',
      headers: buildForwardHeaders(event.request)
    });
    if (!response.ok) {
      fastApiError = `HTTP ${response.status}`;
    } else {
      const data = await response.json();
      return json({
        ...data,
        transport: 'fastapi'
      });
    }
  } catch (e) {
    fastApiError = e instanceof Error ? e.message : String(e);
  }

  const fallback = readLocalProcessWatchLatest(safeMinMb, scope, safeLimit);
  return json({
    ...fallback,
    transport: 'local_fallback',
    error: fastApiError ?? fallback.error ?? null
  });
};
