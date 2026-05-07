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
import {
  buildMergeTestCheckEnv,
  cleanMergeTestCheckOutput,
  isRetryableSvelteKitOutDirFailure,
} from "../scripts/run-merge-test-check.mjs";

const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const mergeTestBuildScript = readFileSync(new URL("../scripts/run-merge-test-build.mjs", import.meta.url), "utf8");
const mergeTestCheckScript = readFileSync(new URL("../scripts/run-merge-test-check.mjs", import.meta.url), "utf8");

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

test("package exposes an isolated merge-test check entrypoint", () => {
  assert.equal(packageJson.scripts["check:merge-test"], "node scripts/run-merge-test-check.mjs");
  assert.match(mergeTestCheckScript, /svelte-kit/);
  assert.match(mergeTestCheckScript, /svelte-check/);
});

test("merge-test check env prefers the isolated outDir", () => {
  const env = buildMergeTestCheckEnv({
    MONITOR_FRONTEND_MODE: "admin",
    MONITOR_SVELTEKIT_OUTDIR: ".svelte-kit-admin",
    MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR: ".isolated-check-kit",
  });

  assert.equal(env.MONITOR_FRONTEND_MODE, "admin");
  assert.equal(env.MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR, ".isolated-check-kit");
  assert.equal(env.MONITOR_SVELTEKIT_OUTDIR, ".isolated-check-kit");
});

test("merge-test check cleanup removes only isolated output", () => {
  const root = mkdtempSync(join(tmpdir(), "monitor-check-merge-"));
  const isolatedOutputDir = join(root, MERGE_TEST_SVELTEKIT_OUTDIR, "output");
  const defaultOutputDir = join(root, ".svelte-kit", "output");
  mkdirSync(isolatedOutputDir, { recursive: true });
  mkdirSync(defaultOutputDir, { recursive: true });
  writeFileSync(join(isolatedOutputDir, "locked.js"), "stale", "utf8");
  writeFileSync(join(defaultOutputDir, "dev.js"), "active", "utf8");

  const cleaned = cleanMergeTestCheckOutput(root, buildMergeTestCheckEnv({}));

  assert.equal(cleaned, isolatedOutputDir);
  assert.equal(existsSync(isolatedOutputDir), false);
  assert.equal(existsSync(defaultOutputDir), true);
});

test("merge-test check retries only permission failures in a SvelteKit outDir", () => {
  assert.equal(
    isRetryableSvelteKitOutDirFailure("EPERM: operation not permitted, unlink '.svelte-kit-merge-test/output/x.js'"),
    true,
  );
  assert.equal(
    isRetryableSvelteKitOutDirFailure("Access is denied: .svelte-kit\\types\\src\\routes\\proxy+page.ts"),
    true,
  );
  assert.equal(
    isRetryableSvelteKitOutDirFailure("src/routes/+page.svelte: Type 'string' is not assignable to type 'number'"),
    false,
  );
});
