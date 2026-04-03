import { json } from '@sveltejs/kit';
import { dev } from '$app/environment';
import type { RequestHandler } from './$types';
import { assertAdminCredential, assertLocalRequest } from '$lib/server/recovery-guard';
import {
  killLocalProcessWatch,
  LocalProcessWatchError,
  type RecoveryProcessWatchKillRequest
} from '$lib/server/process-watch-fallback';

const FASTAPI_KILL_URL = 'http://localhost:8001/api/v1/system/process-watch/kill';

function buildForwardHeaders(req: Request): HeadersInit {
  const headers: HeadersInit = { 'content-type': 'application/json' };
  const auth = req.headers.get('authorization');
  const cookie = req.headers.get('cookie');
  if (auth) headers['authorization'] = auth;
  if (cookie) headers['cookie'] = cookie;
  return headers;
}

export const POST: RequestHandler = async (event) => {
  assertLocalRequest(event);
  assertAdminCredential(event);

  if (!dev) {
    return json(
      {
        success: false,
        code: 'dev_mode_required',
        message: 'process-kill recovery action은 dev 모드에서만 허용됩니다.'
      },
      { status: 403 }
    );
  }

  let payload: RecoveryProcessWatchKillRequest;
  try {
    const body = await event.request.json();
    payload = {
      pid: Number(body?.pid ?? 0),
      expected_create_time: body?.expected_create_time ?? null,
      expected_cmdline_hash: body?.expected_cmdline_hash ?? null,
      reason: String(body?.reason ?? ''),
      force: Boolean(body?.force)
    };
  } catch {
    return json({ success: false, code: 'invalid_json', message: '요청 본문이 올바르지 않습니다.' }, { status: 400 });
  }

  if (!Number.isFinite(payload.pid) || payload.pid <= 0) {
    return json({ success: false, code: 'invalid_pid', message: '유효하지 않은 PID입니다.' }, { status: 400 });
  }

  try {
    const fastapiRes = await fetch(FASTAPI_KILL_URL, {
      method: 'POST',
      headers: buildForwardHeaders(event.request),
      body: JSON.stringify(payload)
    });
    if (fastapiRes.ok) {
      const data = await fastapiRes.json();
      return json({ ...data, transport: 'fastapi' });
    }
  } catch {
    // FastAPI down → local fallback
  }

  try {
    const localResult = killLocalProcessWatch(payload);
    return json({ ...localResult, transport: 'local_fallback' });
  } catch (e) {
    if (e instanceof LocalProcessWatchError) {
      return json(
        {
          success: false,
          code: e.code,
          message: e.message,
          detail: e.detail ?? null
        },
        { status: e.status }
      );
    }
    return json(
      {
        success: false,
        code: 'unknown_error',
        message: e instanceof Error ? e.message : String(e)
      },
      { status: 500 }
    );
  }
};
