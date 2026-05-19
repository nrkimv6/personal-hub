import test from "node:test";
import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const kitWriteTypesPath = new URL(
  "../node_modules/@sveltejs/kit/src/core/sync/write_types/index.js",
  import.meta.url,
);
const patchPath = new URL("../patches/@sveltejs+kit+2.49.0.patch", import.meta.url);

function assertPatchContract() {
  const patch = readFileSync(patchPath, "utf8");
  assert.match(patch, /fs\.readFileSync\(file_path, 'utf8'\)/);
  assert.match(patch, /err\.code === 'ENOENT'/);
  assert.match(patch, /\[svelte-kit-patch\] createProxy ENOENT swallowed:/);
  assert.match(patch, /return null;/);
  assert.match(patch, /throw err;/);
}

async function withWriteTypesProject(routeFile, fn) {
  const previousCwd = process.cwd();
  const root = mkdtempSync(join(tmpdir(), "monitor-sveltekit-write-types-"));
  const routes = join(root, "src", "routes");
  const outDir = join(root, ".svelte-kit");
  const typesDir = join(outDir, "types", "src", "routes");
  mkdirSync(routes, { recursive: true });
  mkdirSync(typesDir, { recursive: true });

  const config = {
    kit: {
      files: {
        params: join(root, "src", "params"),
        routes,
      },
      outDir,
    },
  };
  const leaf = {
    depth: 0,
    parent: null,
    server: null,
    universal: routeFile,
  };
  const manifest = {
    routes: [
      {
        id: "/",
        params: [],
        page: { layouts: [], errors: [], leaf },
        endpoint: null,
        leaf,
        layout: null,
      },
    ],
  };

  try {
    process.chdir(root);
    const moduleUrl = `${pathToFileURL(fileURLToPath(kitWriteTypesPath)).href}?case=${Date.now()}-${Math.random()}`;
    const mod = await import(moduleUrl);
    return await fn({ write_types: mod.write_types, config, manifest, routeFile, typesDir });
  } finally {
    process.chdir(previousCwd);
    rmSync(root, { recursive: true, force: true });
  }
}

test("test_writeTypes_R_generates_types_when_page_ts_exists", async () => {
  if (!existsSync(kitWriteTypesPath)) {
    assertPatchContract();
    return;
  }

  const root = mkdtempSync(join(tmpdir(), "monitor-sveltekit-route-"));
  const routeFile = join(root, "+page.ts");
  writeFileSync(routeFile, "export const load = () => ({ answer: 42 });\n", "utf8");

  await withWriteTypesProject(routeFile, ({ write_types, config, manifest, typesDir }) => {
    write_types(config, manifest, routeFile);
    const types = readFileSync(join(typesDir, "$types.d.ts"), "utf8");
    assert.match(types, /export type PageLoad/);
    assert.match(types, /export type PageData/);
  });

  rmSync(root, { recursive: true, force: true });
});

test("test_writeTypes_E_swallow_enoent_and_generates_unknown_data", async () => {
  if (!existsSync(kitWriteTypesPath)) {
    assertPatchContract();
    return;
  }

  const routeFile = join(tmpdir(), "monitor-missing-+page.ts");

  await withWriteTypesProject(routeFile, ({ write_types, config, manifest, typesDir }) => {
    assert.doesNotThrow(() => write_types(config, manifest, routeFile));
    const types = readFileSync(join(typesDir, "$types.d.ts"), "utf8");
    assert.match(types, /export type PageData/);
    assert.match(types, /unknown/);
  });
});

test("test_writeTypes_E_rethrows_non_enoent_read_error", async () => {
  if (!existsSync(kitWriteTypesPath)) {
    assertPatchContract();
    return;
  }

  const root = mkdtempSync(join(tmpdir(), "monitor-sveltekit-dir-route-"));
  const routeFile = join(root, "+page.ts");
  mkdirSync(routeFile, { recursive: true });

  await withWriteTypesProject(routeFile, ({ write_types, config, manifest }) => {
    assert.throws(() => write_types(config, manifest, routeFile));
  });

  rmSync(root, { recursive: true, force: true });
});

test("test_writeTypes_T3_recovers_after_stale_manifest_file_returns", async () => {
  if (!existsSync(kitWriteTypesPath)) {
    assertPatchContract();
    return;
  }

  const root = mkdtempSync(join(tmpdir(), "monitor-sveltekit-stale-"));
  const routeFile = join(root, "+page.ts");

  await withWriteTypesProject(routeFile, ({ write_types, config, manifest, typesDir }) => {
    assert.doesNotThrow(() => write_types(config, manifest, routeFile));
    let types = readFileSync(join(typesDir, "$types.d.ts"), "utf8");
    assert.match(types, /unknown/);

    mkdirSync(dirname(routeFile), { recursive: true });
    writeFileSync(routeFile, "export const load = () => ({ recovered: true });\n", "utf8");
    assert.doesNotThrow(() => write_types(config, manifest, routeFile));
    types = readFileSync(join(typesDir, "$types.d.ts"), "utf8");
    assert.match(types, /export type PageLoad/);
  });

  rmSync(root, { recursive: true, force: true });
});
