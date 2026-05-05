import { spawnSync } from "node:child_process";

import { MERGE_TEST_SVELTEKIT_OUTDIR } from "./prebuild-clean-sveltekit-output.mjs";

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const outDir = process.env.MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR || MERGE_TEST_SVELTEKIT_OUTDIR;
const env = {
  ...process.env,
  MONITOR_FRONTEND_MODE: process.env.MONITOR_FRONTEND_MODE || "merge-test",
  MONITOR_MERGE_TEST_SVELTEKIT_OUTDIR: outDir,
  MONITOR_SVELTEKIT_OUTDIR: outDir,
};

console.log(`frontend merge-test build: mode=${env.MONITOR_FRONTEND_MODE} outDir=${outDir}`);

const result = spawnSync(npmCommand, ["run", "build"], {
  stdio: "inherit",
  env,
  shell: false,
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
