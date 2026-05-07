import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

import {
  cleanStaleSvelteKitOutput,
  MERGE_TEST_SVELTEKIT_OUTDIR,
} from "./prebuild-clean-sveltekit-output.mjs";

const isWindows = process.platform === "win32";

export function buildMergeTestCheckEnv(env = process.env) {
  const outDir = env.MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR || MERGE_TEST_SVELTEKIT_OUTDIR;
  return {
    ...env,
    MONITOR_FRONTEND_MODE: env.MONITOR_FRONTEND_MODE || "merge-test",
    MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR: outDir,
    MONITOR_SVELTEKIT_OUTDIR: outDir,
  };
}

export function localBinPath(binName, cwd = process.cwd(), platform = process.platform) {
  const suffix = platform === "win32" ? ".cmd" : "";
  return resolve(cwd, "node_modules", ".bin", `${binName}${suffix}`);
}

export function isRetryableSvelteKitOutDirFailure(output, outDir = MERGE_TEST_SVELTEKIT_OUTDIR) {
  const text = String(output || "");
  const hasPermissionFailure = /\b(?:EPERM|EBUSY)\b|Access is denied/i.test(text);
  const mentionsSvelteKitOutDir = text.includes(outDir) || /\.svelte-kit(?:[\\/]|$)/.test(text);
  return hasPermissionFailure && mentionsSvelteKitOutDir;
}

function writeBufferedOutput(result, stdout = process.stdout, stderr = process.stderr) {
  if (result.stdout) stdout.write(result.stdout);
  if (result.stderr) stderr.write(result.stderr);
}

function runLocalBin(binName, args, options) {
  const command = localBinPath(binName, options.cwd);
  if (!existsSync(command)) {
    return {
      status: 127,
      stdout: "",
      stderr: `local binary not found: ${command}\n`,
      error: undefined,
    };
  }

  return options.spawn(command, args, {
    cwd: options.cwd,
    env: options.env,
    encoding: "utf8",
    shell: isWindows,
  });
}

export function runMergeTestCheckOnce({
  cwd = process.cwd(),
  env = buildMergeTestCheckEnv(),
  spawn = spawnSync,
} = {}) {
  const sync = runLocalBin("svelte-kit", ["sync"], { cwd, env, spawn });
  if (sync.error || (sync.status ?? 1) !== 0) {
    return { status: sync.status ?? 1, stdout: sync.stdout || "", stderr: sync.stderr || "", error: sync.error };
  }

  const check = runLocalBin("svelte-check", ["--tsconfig", "./tsconfig.json"], { cwd, env, spawn });
  return { status: check.status ?? 1, stdout: `${sync.stdout || ""}${check.stdout || ""}`, stderr: `${sync.stderr || ""}${check.stderr || ""}`, error: check.error };
}

export function cleanMergeTestCheckOutput(cwd = process.cwd(), env = buildMergeTestCheckEnv()) {
  return cleanStaleSvelteKitOutput(cwd, env);
}

export function runMergeTestCheck({
  cwd = process.cwd(),
  env = buildMergeTestCheckEnv(),
  spawn = spawnSync,
  stdout = process.stdout,
  stderr = process.stderr,
} = {}) {
  const outDir = env.MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR || MERGE_TEST_SVELTEKIT_OUTDIR;
  stdout.write(`frontend merge-test check: mode=${env.MONITOR_FRONTEND_MODE} outDir=${outDir}\n`);

  const first = runMergeTestCheckOnce({ cwd, env, spawn });
  writeBufferedOutput(first, stdout, stderr);

  const firstOutput = `${first.stdout || ""}${first.stderr || ""}${first.error?.message || ""}`;
  if (!first.error && (first.status ?? 1) === 0) {
    return 0;
  }

  if (!isRetryableSvelteKitOutDirFailure(firstOutput, outDir)) {
    if (first.error) stderr.write(`${first.error.message}\n`);
    return first.status ?? 1;
  }

  const cleaned = cleanMergeTestCheckOutput(cwd, env);
  stderr.write(`retrying merge-test check after cleaning stale SvelteKit output: ${cleaned}\n`);

  const retry = runMergeTestCheckOnce({ cwd, env, spawn });
  writeBufferedOutput(retry, stdout, stderr);
  if (retry.error) stderr.write(`${retry.error.message}\n`);
  return retry.status ?? 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(runMergeTestCheck());
}
