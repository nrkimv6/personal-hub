import { rmSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const MERGE_TEST_SVELTEKIT_OUTDIR = ".svelte-kit-merge-test";

export function resolveSvelteKitOutDir(env = process.env) {
  if (env.MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR) return env.MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR;
  if (env.MONITOR_SVELTEKIT_OUTDIR) return env.MONITOR_SVELTEKIT_OUTDIR;
  if (env.MONITOR_FRONTEND_MODE === "public") return ".svelte-kit-public";
  if (env.MONITOR_FRONTEND_MODE === "admin") return ".svelte-kit-admin";
  return ".svelte-kit";
}

export function cleanStaleSvelteKitOutput(cwd = process.cwd(), env = process.env) {
  const outDir = resolveSvelteKitOutDir(env);
  const outputDir = resolve(cwd, outDir, "output");
  rmSync(outputDir, { recursive: true, force: true });
  return outputDir;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const cleaned = cleanStaleSvelteKitOutput();
  console.log(`cleaned stale SvelteKit output: ${cleaned}`);
}
