import { error } from '@sveltejs/kit';
import type { RequestEvent } from '@sveltejs/kit';

const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', 'localhost']);

function normalizeHost(raw: string | null | undefined): string {
  if (!raw) return '';
  return raw.replace('::ffff:', '').trim().toLowerCase();
}

export function getClientHost(event: RequestEvent): string {
  const direct = normalizeHost(event.getClientAddress?.());
  if (direct) return direct;

  const xff = event.request.headers.get('x-forwarded-for');
  if (xff) {
    const first = xff.split(',')[0]?.trim();
    return normalizeHost(first);
  }

  const realIp = event.request.headers.get('x-real-ip');
  if (realIp) return normalizeHost(realIp);
  return '';
}

export function assertLocalRequest(event: RequestEvent): void {
  const host = getClientHost(event);
  if (!LOOPBACK_HOSTS.has(host)) {
    throw error(403, `Recovery route is localhost-only (client=${host || 'unknown'})`);
  }
}

export function hasAdminCredential(event: RequestEvent): boolean {
  const authHeader = event.request.headers.get('authorization') || '';
  if (authHeader.toLowerCase().startsWith('bearer ')) return true;

  const cookieToken = event.cookies.get('auth_token');
  if (cookieToken && cookieToken.length > 0) return true;

  const recoveryToken = event.request.headers.get('x-recovery-admin-token');
  const expected = process.env.RECOVERY_ADMIN_TOKEN;
  if (expected && recoveryToken === expected) return true;

  return false;
}

export function assertAdminCredential(event: RequestEvent): void {
  if (!hasAdminCredential(event)) {
    throw error(403, '관리자 토큰/쿠키가 필요합니다.');
  }
}
