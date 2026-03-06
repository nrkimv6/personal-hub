<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { CheckCircle2, XCircle, Circle } from 'lucide-svelte';

  interface ZombieProcess {
    pid: number;
    started: string;
    memory_mb: number;
    runtime_hours: number;
    is_zombie: boolean;
  }

  interface DeathInfo {
    timestamp: string;
    cause: string;
    exit_code: number;
    crash_loop_count: number;
  }

  interface DiagnosticResult {
    timestamp: string;
    status: string;
    severity: string;
    message: string;
    action: string;
    details: {
      api_port: number;
      port_listening: boolean | null;
      python_ok: boolean | null;
      sqlalchemy_ok: boolean | null;
      db_ok: boolean | null;
      import_ok: boolean | null;
      import_error_message: string | null;
      zombie_processes: ZombieProcess[];
      last_death: DeathInfo | null;
    };
  }

  interface ProcessStatus {
    timestamp: string;
    healthy: boolean;
    pid: number;
    connections: {
      listen: number;
      established: number;
      close_wait: number;
      time_wait: number;
    };
    memory_mb: number;
    cpu_seconds: number;
    uptime_hours: number;
  }

  let diagnostic = $state<DiagnosticResult | null>(null);
  let processStatus = $state<ProcessStatus | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let pollTimer: ReturnType<typeof setInterval> | undefined;

  const severityBadge: Record<string, string> = {
    critical: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
    error: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
    warning: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
    ok: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
  };

  type StepStatus = 'pass' | 'fail' | 'skip';

  interface DiagStep {
    label: string;
    status: StepStatus;
  }

  function getSteps(d: DiagnosticResult): DiagStep[] {
    const det = d.details;
    return [
      { label: 'API 헬스체크', status: d.status === 'api_healthy' ? 'pass' : 'fail' },
      { label: `포트 ${det.api_port} LISTEN`, status: det.port_listening === null ? 'skip' : det.port_listening ? 'fail' : 'pass' },
      { label: 'Python 기본 실행', status: det.python_ok === null ? 'skip' : det.python_ok ? 'pass' : 'fail' },
      { label: 'SQLAlchemy import', status: det.sqlalchemy_ok === null ? 'skip' : det.sqlalchemy_ok ? 'pass' : 'fail' },
      { label: 'DB 연결', status: det.db_ok === null ? 'skip' : det.db_ok ? 'pass' : 'fail' },
      { label: 'app.main import', status: det.import_ok === null ? 'skip' : det.import_ok ? 'pass' : 'fail' }
    ];
  }

  async function fetchProcessStatus() {
    try {
      const res = await fetch('/process-status.json?t=' + Date.now());
      if (res.ok) {
        processStatus = await res.json();
      } else {
        processStatus = null;
      }
    } catch {
      processStatus = null;
    }
  }

  async function fetchDiagnostics() {
    try {
      const res = await fetch('/diagnostics.json?t=' + Date.now());
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'api_healthy') {
          diagnostic = null;
        } else {
          diagnostic = data;
        }
        error = null;
      } else {
        error = `HTTP ${res.status}`;
      }
    } catch {
      diagnostic = null;
      error = 'diagnostics.json을 불러올 수 없습니다.';
    }
    loading = false;
  }

  onMount(() => {
    fetchDiagnostics();
    fetchProcessStatus();
    pollTimer = setInterval(() => { fetchDiagnostics(); fetchProcessStatus(); }, 30000);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });
</script>

<div class="space-y-6">
  {#if loading}
    <div class="bg-card rounded-lg border border-border p-6 animate-pulse">
      <div class="h-6 bg-muted rounded w-1/3 mb-4"></div>
      <div class="h-4 bg-muted rounded w-2/3"></div>
    </div>
  {:else if !diagnostic}
    <div class="bg-card rounded-lg border border-border p-6 text-center text-muted-foreground">
      <p class="text-lg mb-2">진단 정보 없음</p>
      <p class="text-sm">
        {#if error}
          {error}
        {:else}
          API가 정상이거나 진단이 실행되지 않았습니다.
        {/if}
      </p>
      <p class="text-xs mt-3 font-mono bg-muted rounded px-3 py-2 inline-block">
        .\scripts\diagnose-api.ps1 -Dev
      </p>
    </div>
  {:else}
    <!-- 상태 요약 -->
    <div class="bg-card rounded-lg border border-border p-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-foreground">진단 결과</h3>
        <span class="text-xs text-muted-foreground">{diagnostic.timestamp}</span>
      </div>

      <div class="flex items-center gap-3 mb-3">
        <span class="px-3 py-1 rounded-full text-sm font-medium {severityBadge[diagnostic.severity] || ''}">
          {diagnostic.status}
        </span>
        <span class="text-foreground">{diagnostic.message}</span>
      </div>

      {#if diagnostic.action}
        <div class="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded px-4 py-2 text-sm text-yellow-800 dark:text-yellow-200">
          <strong>조치:</strong> {diagnostic.action}
        </div>
      {/if}
    </div>

    <!-- 단계별 결과 -->
    <div class="bg-card rounded-lg border border-border p-6">
      <h3 class="text-lg font-semibold text-foreground mb-4">진단 단계</h3>
      <div class="space-y-2">
        {#each getSteps(diagnostic) as step}
          <div class="flex items-center gap-3 py-1.5 px-3 rounded {step.status === 'fail' ? 'bg-red-50 dark:bg-red-900/10' : ''}">
            <span>
              {#if step.status === 'pass'}
                <CheckCircle2 class="w-4 h-4 text-green-500" />
              {:else if step.status === 'fail'}
                <XCircle class="w-4 h-4 text-red-500" />
              {:else}
                <Circle class="w-4 h-4 text-gray-300" />
              {/if}
            </span>
            <span class="text-sm text-foreground">{step.label}</span>
          </div>
        {/each}
      </div>
    </div>

    <!-- Import 에러 메시지 -->
    {#if diagnostic.details.import_error_message}
      <div class="bg-card rounded-lg border border-border p-6">
        <h3 class="text-lg font-semibold text-foreground mb-3">Import 에러</h3>
        <pre class="bg-muted rounded p-4 text-xs text-foreground overflow-x-auto whitespace-pre-wrap">{diagnostic.details.import_error_message}</pre>
      </div>
    {/if}

    <!-- Zombie 프로세스 -->
    {#if diagnostic.details.zombie_processes.length > 0}
      <div class="bg-card rounded-lg border border-border p-6">
        <h3 class="text-lg font-semibold text-foreground mb-3">Python 프로세스 ({diagnostic.details.zombie_processes.length})</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-border text-left text-muted-foreground">
                <th class="py-2 px-3">PID</th>
                <th class="py-2 px-3">시작 시간</th>
                <th class="py-2 px-3">메모리</th>
                <th class="py-2 px-3">실행 시간</th>
                <th class="py-2 px-3">상태</th>
              </tr>
            </thead>
            <tbody>
              {#each diagnostic.details.zombie_processes as proc}
                <tr class="border-b border-border/50 {proc.is_zombie ? 'bg-red-50 dark:bg-red-900/10' : ''}">
                  <td class="py-2 px-3 font-mono">{proc.pid}</td>
                  <td class="py-2 px-3">{proc.started}</td>
                  <td class="py-2 px-3">{proc.memory_mb} MB</td>
                  <td class="py-2 px-3">{proc.runtime_hours}h</td>
                  <td class="py-2 px-3">
                    {#if proc.is_zombie}
                      <span class="px-2 py-0.5 rounded text-xs bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300">ZOMBIE</span>
                    {:else}
                      <span class="text-muted-foreground">정상</span>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}

    <!-- 마지막 사망 기록 -->
    {#if diagnostic.details.last_death}
      {@const death = diagnostic.details.last_death}
      <div class="bg-card rounded-lg border border-border p-6">
        <h3 class="text-lg font-semibold text-foreground mb-3">마지막 사망 기록</h3>
        <dl class="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt class="text-muted-foreground">시간</dt>
            <dd class="text-foreground font-mono">{death.timestamp}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">원인</dt>
            <dd class="text-foreground">{death.cause}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">종료 코드</dt>
            <dd class="text-foreground font-mono">{death.exit_code}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">크래시 루프</dt>
            <dd class="text-foreground {death.crash_loop_count > 0 ? 'text-red-600 font-bold' : ''}">{death.crash_loop_count}회 (최근 5분)</dd>
          </div>
        </dl>
      </div>
    {/if}

    <!-- 다시 진단 -->
    <div class="text-center">
      <button
        onclick={() => { loading = true; fetchDiagnostics(); }}
        class="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm"
      >
        다시 진단 (JSON 리로드)
      </button>
    </div>
  {/if}

  <!-- 프로세스 상태 (watchdog에서 수집) -->
  {#if processStatus}
    <div class="bg-card rounded-lg border border-border p-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-foreground">프로세스 상태</h3>
        <div class="flex items-center gap-2">
          <span class="inline-block w-2 h-2 rounded-full {processStatus.healthy ? 'bg-green-500' : 'bg-red-500'}"></span>
          <span class="text-xs text-muted-foreground">{processStatus.timestamp}</span>
        </div>
      </div>

      <dl class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
        <div>
          <dt class="text-muted-foreground">PID</dt>
          <dd class="text-foreground font-mono">{processStatus.pid || '-'}</dd>
        </div>
        <div>
          <dt class="text-muted-foreground">가동시간</dt>
          <dd class="text-foreground">{processStatus.uptime_hours}h</dd>
        </div>
        <div>
          <dt class="text-muted-foreground">메모리</dt>
          <dd class="text-foreground {processStatus.memory_mb >= 500 ? 'text-red-600 font-bold' : ''}">{processStatus.memory_mb} MB</dd>
        </div>
        <div>
          <dt class="text-muted-foreground">CPU</dt>
          <dd class="text-foreground">{processStatus.cpu_seconds}s</dd>
        </div>
      </dl>

      {#if processStatus.pid}
        <div class="mt-4">
          <h4 class="text-sm font-medium text-muted-foreground mb-2">TCP 연결</h4>
          <div class="flex gap-4 text-sm">
            <span class="px-2 py-1 rounded bg-muted">Listen <strong>{processStatus.connections.listen}</strong></span>
            <span class="px-2 py-1 rounded bg-muted">Established <strong>{processStatus.connections.established}</strong></span>
            <span class="px-2 py-1 rounded {processStatus.connections.close_wait > 10 ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300' : 'bg-muted'}">CloseWait <strong>{processStatus.connections.close_wait}</strong></span>
            <span class="px-2 py-1 rounded bg-muted">TimeWait <strong>{processStatus.connections.time_wait}</strong></span>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
