import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  cleanStaleSvelteKitOutput,
  resolveSvelteKitOutDir,
} from "../scripts/prebuild-clean-sveltekit-output.mjs";

test("prebuild cleanup targets the active SvelteKit outDir", () => {
  assert.equal(resolveSvelteKitOutDir({ MONITOR_SVELTEKIT_OUTDIR: ".custom-kit" }), ".custom-kit");
  assert.equal(resolveSvelteKitOutDir({ MONITOR_FRONTEND_MODE: "public" }), ".svelte-kit-public");
  assert.equal(resolveSvelteKitOutDir({ MONITOR_FRONTEND_MODE: "admin" }), ".svelte-kit-admin");
  assert.equal(resolveSvelteKitOutDir({}), ".svelte-kit");
});

test("prebuild cleanup removes only stale output and keeps generated config", () => {
  const root = mkdtempSync(join(tmpdir(), "monitor-prebuild-"));
  const outputDir = join(root, ".svelte-kit-public", "output");
  const tsconfigPath = join(root, ".svelte-kit-public", "tsconfig.json");
  mkdirSync(outputDir, { recursive: true });
  writeFileSync(join(outputDir, "server-internal-stale.txt"), "stale", "utf8");
  writeFileSync(tsconfigPath, "{}", "utf8");

  const cleaned = cleanStaleSvelteKitOutput(root, { MONITOR_FRONTEND_MODE: "public" });

  assert.equal(cleaned, outputDir);
  assert.equal(existsSync(outputDir), false);
  assert.equal(existsSync(tsconfigPath), true);
});
