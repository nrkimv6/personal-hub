<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { AlertCircle, AlertTriangle, CheckCircle, X, HelpCircle } from 'lucide-svelte';

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
      zombie_processes: Array<{ pid: number; started: string; memory_mb: number; runtime_hours: number; is_zombie: boolean }>;
      last_death: { timestamp: string; cause: string; exit_code: number; crash_loop_count: number } | null;
    };
  }

  let diagnostic = $state<DiagnosticResult | null>(null);
  let dismissed = $state(false);
  let pollTimer: ReturnType<typeof setInterval> | undefined;

  const severityColors: Record<string, string> = {
    critical: 'bg-red-600 text-white border-red-700',
    error: 'bg-orange-500 text-white border-orange-600',
    warning: 'bg-yellow-400 text-yellow-900 border-yellow-500',
    ok: ''
  };

  const severityIcons: Record<string, any> = {
    critical: AlertCircle,
    error: AlertTriangle,
    warning: AlertTriangle,
    ok: CheckCircle
  };

  async function fetchDiagnostics() {
    try {
      const res = await fetch('/diagnostics.json?t=' + Date.now());
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'api_healthy') {
          diagnostic = null;
        } else {
          diagnostic = data;
          dismissed = false;
        }
      }
    } catch {
      // File doesn't exist or server down — no diagnostic available
    }
  }

  onMount(() => {
    fetchDiagnostics();
    pollTimer = setInterval(fetchDiagnostics, 30000);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });
</script>

{#if diagnostic && diagnostic.status !== 'api_healthy' && !dismissed}
  {@const colors = severityColors[diagnostic.severity] || severityColors.error}
  {@const Icon = severityIcons[diagnostic.severity] || HelpCircle}
  <div class="px-4 py-3 border-b {colors} flex items-center justify-between gap-3">
    <div class="flex items-center gap-3 min-w-0">
      <div class="flex-shrink-0 flex items-center">
        <Icon size={20} strokeWidth={2.5} />
      </div>
      <div class="min-w-0">
        <span class="font-semibold">{diagnostic.status}</span>
        <span class="mx-1">—</span>
        <span>{diagnostic.message}</span>
        {#if diagnostic.action}
          <span class="ml-2 opacity-80">({diagnostic.action})</span>
        {/if}
      </div>
    </div>
    <button
      onclick={() => (dismissed = true)}
      class="flex-shrink-0 opacity-70 hover:opacity-100 transition-opacity flex items-center justify-center"
      aria-label="닫기"
    >
      <X size={18} />
    </button>
  </div>
{/if}
