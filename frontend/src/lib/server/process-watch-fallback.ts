import { createHash } from 'crypto';
import { execFileSync } from 'child_process';
import { appendFileSync, existsSync, readFileSync } from 'fs';
import { join, resolve } from 'path';

export interface RecoveryProcessWatchItem {
  captured_at: string;
  pid: number;
  ppid: number | null;
  parent_pid: number | null;
  parent_name: string;
  name: string;
  exe: string;
  cmdline: string;
  cmdline_hash: string;
  create_time: number | null;
  memory_mb: number;
  is_orphan: boolean;
  scope: string;
  captured_by: string;
}

export interface RecoveryProcessWatchLatest {
  captured_at: string | null;
  source: 'jsonl_fallback' | 'live_scan';
  snapshot_age_seconds: number | null;
  stale: boolean;
  item_count: number;
  items: RecoveryProcessWatchItem[];
  error?: string | null;
}

export interface RecoveryProcessWatchKillRequest {
  pid: number;
  expected_create_time?: number | null;
  expected_cmdline_hash?: string | null;
  reason: string;
  force: boolean;
}

export interface RecoveryProcessWatchKillResponse {
  success: boolean;
  pid: number;
  result_code: string;
  message: string;
  scope: string;
  cmdline_hash: string;
}

export class LocalProcessWatchError extends Error {
  status: number;
  code: string;
  detail: Record<string, unknown>;

  constructor(status: number, code: string, message: string, detail: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function resolveProjectRoot(): string {
  const candidates = [process.cwd(), resolve(process.cwd(), '..')];
  for (const candidate of candidates) {
    if (existsSync(join(candidate, 'app')) && existsSync(join(candidate, 'logs'))) {
      return candidate;
    }
  }
  return process.cwd();
}

const PROJECT_ROOT = resolveProjectRoot();
const WATCH_EVENTS_LOG = join(PROJECT_ROOT, 'logs', 'process_watch_events.jsonl');
const KILL_AUDIT_LOG = join(PROJECT_ROOT, 'logs', 'process_watch_kill_audit.jsonl');

function cmdlineHash(cmdline: string): string {
  const normalized = (cmdline || '').trim();
  if (!normalized) return '';
  return createHash('sha256').update(normalized).digest('hex').slice(0, 32);
}

function inferScope(name: string, exe: string, cmdline: string): string {
  const joined = `${name || ''} ${exe || ''} ${cmdline || ''}`.toLowerCase().replaceAll('\\', '/');
  const rootHint = PROJECT_ROOT.toLowerCase().replaceAll('\\', '/');
  if (joined.includes(rootHint)) return 'monitor_page';
  if (joined.includes('monitor-page') || joined.includes('browser_workers.py') || joined.includes('app/main.py')) {
    return 'monitor_page';
  }
  return 'external';
}

function normalizeItems(
  rawItems: Array<Record<string, unknown>>,
  opts: { minMb: number; scope?: string; limit: number; capturedAt: string; capturedBy: string }
): RecoveryProcessWatchItem[] {
  const rows = rawItems
    .map((row) => {
      const cmdline = String(row.cmdline ?? '');
      const name = String(row.name ?? '');
      const exe = String(row.exe ?? '');
      return {
        captured_at: String(row.captured_at ?? opts.capturedAt),
        pid: Number(row.pid ?? 0),
        ppid: row.ppid === null || row.ppid === undefined ? null : Number(row.ppid),
        parent_pid: row.parent_pid === null || row.parent_pid === undefined ? null : Number(row.parent_pid),
        parent_name: String(row.parent_name ?? ''),
        name,
        exe,
        cmdline,
        cmdline_hash: String(row.cmdline_hash ?? cmdlineHash(cmdline)),
        create_time: row.create_time === null || row.create_time === undefined ? null : Number(row.create_time),
        memory_mb: Number(row.memory_mb ?? 0),
        is_orphan: Boolean(row.is_orphan),
        scope: String(row.scope ?? inferScope(name, exe, cmdline)),
        captured_by: String(row.captured_by ?? opts.capturedBy)
      } as RecoveryProcessWatchItem;
    })
    .filter((item) => item.pid > 0 && item.memory_mb >= opts.minMb)
    .filter((item) => !opts.scope || item.scope === opts.scope)
    .sort((a, b) => b.memory_mb - a.memory_mb);

  return rows.slice(0, Math.max(1, opts.limit));
}

function runPowerShellJson(script: string): unknown {
  const output = execFileSync(
    'powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
    {
      cwd: PROJECT_ROOT,
      encoding: 'utf-8',
      timeout: 20000,
      stdio: ['ignore', 'pipe', 'pipe']
    }
  ).trim();
  if (!output) return [];
  return JSON.parse(output);
}

function readJsonlSnapshot(minMb: number, scope: string | undefined, limit: number): RecoveryProcessWatchLatest | null {
  if (!existsSync(WATCH_EVENTS_LOG)) return null;
  const lines = readFileSync(WATCH_EVENTS_LOG, 'utf-8').split(/\r?\n/).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    try {
      const row = JSON.parse(lines[i]) as { event?: string; timestamp?: string; items?: Array<Record<string, unknown>> };
      if (row.event !== 'snapshot' || !Array.isArray(row.items)) continue;
      const capturedAt = row.timestamp ?? new Date().toISOString();
      const normalized = normalizeItems(row.items, {
        minMb,
        scope,
        limit,
        capturedAt,
        capturedBy: 'jsonl_fallback'
      });
      const age = Math.max(0, Math.floor((Date.now() - new Date(capturedAt).getTime()) / 1000));
      return {
        captured_at: capturedAt,
        source: 'jsonl_fallback',
        snapshot_age_seconds: Number.isFinite(age) ? age : null,
        stale: age > 120,
        item_count: normalized.length,
        items: normalized
      };
    } catch {
      continue;
    }
  }
  return null;
}

function collectLivePythonProcesses(minMb: number, scope: string | undefined, limit: number): RecoveryProcessWatchLatest {
  const psScript = `
$ErrorActionPreference = 'Stop'
$rows = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
  $pid = [int]$_.ProcessId
  $ppid = if ($_.ParentProcessId) { [int]$_.ParentProcessId } else { $null }
  $parentName = $null
  if ($ppid) {
    try {
      $parentName = (Get-Process -Id $ppid -ErrorAction Stop).ProcessName + '.exe'
    } catch {}
  }
  $create = $null
  try {
    $proc = Get-Process -Id $pid -ErrorAction Stop
    $create = [double]([DateTimeOffset]$proc.StartTime).ToUnixTimeSeconds()
  } catch {}
  $orphan = $false
  if ($ppid) {
    $parentAlive = Get-Process -Id $ppid -ErrorAction SilentlyContinue
    $orphan = [bool](-not $parentAlive)
  }
  [pscustomobject]@{
    pid = $pid
    ppid = $ppid
    parent_pid = $null
    parent_name = $parentName
    name = $_.Name
    exe = $_.ExecutablePath
    cmdline = $_.CommandLine
    create_time = $create
    memory_mb = [math]::Round(([double]$_.WorkingSetSize / 1MB), 2)
    is_orphan = $orphan
    scope = $null
    captured_by = 'live_scan'
  }
}
$rows | Sort-Object memory_mb -Descending | Select-Object -First ${Math.max(1, limit)} | ConvertTo-Json -Depth 5
`;
  const result = runPowerShellJson(psScript);
  const rows = Array.isArray(result) ? result : (result ? [result] : []);
  const capturedAt = new Date().toISOString();
  const normalized = normalizeItems(rows as Array<Record<string, unknown>>, {
    minMb,
    scope,
    limit,
    capturedAt,
    capturedBy: 'live_scan'
  });
  return {
    captured_at: capturedAt,
    source: 'live_scan',
    snapshot_age_seconds: 0,
    stale: false,
    item_count: normalized.length,
    items: normalized
  };
}

export function readLocalProcessWatchLatest(minMb: number, scope: string | undefined, limit: number): RecoveryProcessWatchLatest {
  const fromJsonl = readJsonlSnapshot(minMb, scope, limit);
  if (fromJsonl) return fromJsonl;
  return collectLivePythonProcesses(minMb, scope, limit);
}

function getLiveProcess(pid: number): RecoveryProcessWatchItem | null {
  const script = `
$ErrorActionPreference = 'Stop'
$proc = Get-CimInstance Win32_Process -Filter "ProcessId=${pid}"
if (-not $proc) { 'null'; exit 0 }
$ppid = if ($proc.ParentProcessId) { [int]$proc.ParentProcessId } else { $null }
$parentName = $null
if ($ppid) {
  try { $parentName = (Get-Process -Id $ppid -ErrorAction Stop).ProcessName + '.exe' } catch {}
}
$create = $null
try {
  $p = Get-Process -Id ${pid} -ErrorAction Stop
  $create = [double]([DateTimeOffset]$p.StartTime).ToUnixTimeSeconds()
} catch {}
$orphan = $false
if ($ppid) {
  $parentAlive = Get-Process -Id $ppid -ErrorAction SilentlyContinue
  $orphan = [bool](-not $parentAlive)
}
[pscustomobject]@{
  pid = [int]$proc.ProcessId
  ppid = $ppid
  parent_pid = $null
  parent_name = $parentName
  name = $proc.Name
  exe = $proc.ExecutablePath
  cmdline = $proc.CommandLine
  create_time = $create
  memory_mb = [math]::Round(([double]$proc.WorkingSetSize / 1MB), 2)
  is_orphan = $orphan
  scope = $null
  captured_by = 'live_scan'
  captured_at = '${new Date().toISOString()}'
} | ConvertTo-Json -Depth 5
`;
  const parsed = runPowerShellJson(script);
  if (parsed === null || parsed === 'null' || !parsed) return null;
  const rows = Array.isArray(parsed) ? parsed : [parsed];
  const normalized = normalizeItems(rows as Array<Record<string, unknown>>, {
    minMb: 0,
    scope: undefined,
    limit: 1,
    capturedAt: new Date().toISOString(),
    capturedBy: 'live_scan'
  });
  return normalized[0] ?? null;
}

function appendKillAudit(
  payload: RecoveryProcessWatchKillRequest,
  result: string,
  item: RecoveryProcessWatchItem | null,
  detail = ''
): void {
  const row = {
    timestamp: new Date().toISOString(),
    event: 'kill',
    action: 'recovery_process_kill',
    pid: payload.pid,
    cmdline_hash: item?.cmdline_hash ?? payload.expected_cmdline_hash ?? '',
    reason: payload.reason ?? '',
    actor: 'recovery_local',
    result,
    detail
  };
  appendFileSync(KILL_AUDIT_LOG, `${JSON.stringify(row)}\n`, 'utf-8');
}

export function killLocalProcessWatch(payload: RecoveryProcessWatchKillRequest): RecoveryProcessWatchKillResponse {
  const item = getLiveProcess(payload.pid);
  if (!item) {
    appendKillAudit(payload, 'not_found', null, 'PID not found');
    throw new LocalProcessWatchError(404, 'not_found', `PID ${payload.pid} 프로세스를 찾을 수 없습니다.`);
  }

  if (payload.pid <= 4 || payload.pid === process.pid) {
    appendKillAudit(payload, 'blocked', item, 'protected_pid');
    throw new LocalProcessWatchError(403, 'protected_pid', `보호된 PID(${payload.pid})는 종료할 수 없습니다.`);
  }

  if (!item.name.toLowerCase().includes('python')) {
    appendKillAudit(payload, 'blocked', item, 'not_python');
    throw new LocalProcessWatchError(400, 'not_python', `Python 프로세스가 아닙니다 (name=${item.name}).`);
  }

  if (payload.expected_create_time !== undefined && payload.expected_create_time !== null) {
    if (item.create_time !== payload.expected_create_time) {
      appendKillAudit(payload, 'blocked', item, 'fingerprint_mismatch:create_time');
      throw new LocalProcessWatchError(
        409,
        'fingerprint_mismatch',
        'create_time이 일치하지 않습니다.',
        { current_create_time: item.create_time, current_cmdline_hash: item.cmdline_hash }
      );
    }
  }

  if (payload.expected_cmdline_hash && payload.expected_cmdline_hash !== item.cmdline_hash) {
    appendKillAudit(payload, 'blocked', item, 'fingerprint_mismatch:cmdline_hash');
    throw new LocalProcessWatchError(
      409,
      'fingerprint_mismatch',
      'cmdline_hash가 일치하지 않습니다.',
      { current_create_time: item.create_time, current_cmdline_hash: item.cmdline_hash }
    );
  }

  if (item.scope !== 'monitor_page') {
    if (!payload.force) {
      appendKillAudit(payload, 'blocked', item, 'forbidden_scope');
      throw new LocalProcessWatchError(403, 'forbidden_scope', '외부 scope 프로세스는 force=true가 필요합니다.');
    }
    if ((payload.reason || '').trim().length < 8) {
      appendKillAudit(payload, 'blocked', item, 'reason_required');
      throw new LocalProcessWatchError(400, 'reason_required', 'force 종료는 8자 이상의 사유가 필요합니다.');
    }
  }

  const killScript = `Stop-Process -Id ${payload.pid} -Force -ErrorAction Stop`;
  try {
    execFileSync(
      'powershell.exe',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', killScript],
      { cwd: PROJECT_ROOT, encoding: 'utf-8', timeout: 10000, stdio: ['ignore', 'pipe', 'pipe'] }
    );
  } catch (e) {
    appendKillAudit(payload, 'failed', item, String(e));
    throw new LocalProcessWatchError(500, 'kill_failed', `PID ${payload.pid} 종료 실패`);
  }

  appendKillAudit(payload, 'success', item, `scope=${item.scope}`);
  return {
    success: true,
    pid: payload.pid,
    result_code: 'killed',
    message: `PID ${payload.pid} 프로세스를 종료했습니다.`,
    scope: item.scope,
    cmdline_hash: item.cmdline_hash
  };
}
