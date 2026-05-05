import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  cleanStaleSvelteKitOutput,
  MERGE_TEST_SVELTEKIT_OUTDIR,
  resolveSvelteKitOutDir,
} from "../scripts/prebuild-clean-sveltekit-output.mjs";

const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const mergeTestBuildScript = readFileSync(new URL("../scripts/run-merge-test-build.mjs", import.meta.url), "utf8");

test("prebuild cleanup targets the active SvelteKit outDir", () => {
  assert.equal(
    resolveSvelteKitOutDir({ MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR: ".isolated-merge-kit" }),
    ".isolated-merge-kit",
  );
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

test("merge-test cleanup removes only the isolated merge-test output", () => {
  const root = mkdtempSync(join(tmpdir(), "monitor-prebuild-merge-"));
  const mergeOutputDir = join(root, MERGE_TEST_SVELTEKIT_OUTDIR, "output");
  const devOutputDir = join(root, ".svelte-kit-admin", "output");
  const publicOutputDir = join(root, ".svelte-kit-public", "output");
  mkdirSync(mergeOutputDir, { recursive: true });
  mkdirSync(devOutputDir, { recursive: true });
  mkdirSync(publicOutputDir, { recursive: true });
  writeFileSync(join(mergeOutputDir, "stale-start.js"), "stale", "utf8");
  writeFileSync(join(devOutputDir, "dev-server-start.js"), "active", "utf8");
  writeFileSync(join(publicOutputDir, "preview-start.js"), "active", "utf8");

  const cleaned = cleanStaleSvelteKitOutput(root, {
    MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR: MERGE_TEST_SVELTEKIT_OUTDIR,
    MONITOR_SVELTEKIT_OUTDIR: ".svelte-kit-admin",
  });

  assert.equal(cleaned, mergeOutputDir);
  assert.equal(existsSync(mergeOutputDir), false);
  assert.equal(existsSync(devOutputDir), true);
  assert.equal(existsSync(publicOutputDir), true);
});

test("package exposes an isolated merge-test build entrypoint", () => {
  assert.equal(packageJson.scripts["build:merge-test"], "node scripts/run-merge-test-build.mjs");
  assert.equal(MERGE_TEST_SVELTEKIT_OUTDIR, ".svelte-kit-merge-test");
  assert.match(mergeTestBuildScript, /shell:\s*process\.platform === "win32"/);
});
