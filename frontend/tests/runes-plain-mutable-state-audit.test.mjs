import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { relative } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const srcRoot = fileURLToPath(new URL("../src", import.meta.url));

const auditedFiles = [
  "routes/crawl/schedules/[id]/runs/+page.svelte",
  "routes/collect/schedule/+page.svelte",
  "routes/plans/PathManager.svelte",
  "routes/classify/categories/+page.svelte",
];

const allowedPlainLets = new Map([
  [
    "routes/collect/schedule/+page.svelte",
    new Set([
      // Component ref updated by bind:this, not display state.
      "settingsRef",
    ]),
  ],
]);

function normalizePath(path) {
  return relative(srcRoot, path).replaceAll("\\", "/");
}

function scriptAndMarkup(source) {
  const match = source.match(/<script\b[^>]*>([\s\S]*?)<\/script>([\s\S]*)/);
  return {
    script: match?.[1] ?? "",
    markup: match?.[2] ?? source,
  };
}

function stripLineComments(line) {
  return line.replace(/\/\/.*$/, "");
}

function braceDelta(line) {
  const cleaned = stripLineComments(line)
    .replace(/'[^'\\]*(?:\\.[^'\\]*)*'/g, "''")
    .replace(/"[^"\\]*(?:\\.[^"\\]*)*"/g, '""')
    .replace(/`[^`\\]*(?:\\.[^`\\]*)*`/g, "``");
  return (cleaned.match(/\{/g) ?? []).length - (cleaned.match(/\}/g) ?? []).length;
}

function collectTopLevelLets(source) {
  const { script, markup } = scriptAndMarkup(source);
  const lines = script.split(/\r?\n/);
  const declarations = [];
  let depth = 0;

  lines.forEach((line, index) => {
    const depthBefore = depth;
    const match = line.match(/^\s*let\s+([A-Za-z_$][\w$]*)\b/);
    if (depthBefore === 0 && match) {
      declarations.push({
        name: match[1],
        line: index + 1,
        statement: line.trim(),
        usesRune:
          line.includes("$state") ||
          line.includes("$derived") ||
          line.includes("$props"),
        referencedInMarkup: new RegExp(`\\b${match[1]}\\b`).test(markup),
      });
    }
    depth = Math.max(0, depth + braceDelta(line));
  });

  return declarations;
}

function collectPlainMutableStateFailures(filePath) {
  const source = readFileSync(filePath, "utf8");
  if (!/\$(state|derived|props|effect)\b/.test(source)) {
    return [];
  }

  const displayPath = normalizePath(filePath);
  const allowed = allowedPlainLets.get(displayPath) ?? new Set();

  return collectTopLevelLets(source)
    .filter((decl) => decl.referencedInMarkup)
    .filter((decl) => !decl.usesRune)
    .filter((decl) => !allowed.has(decl.name))
    .map((decl) => `${displayPath}:${decl.line} ${decl.name}: ${decl.statement}`);
}

test("audited runes files do not keep displayed mutable state in plain let declarations", () => {
  const failures = auditedFiles.flatMap((file) =>
    collectPlainMutableStateFailures(fileURLToPath(new URL(`../src/${file}`, import.meta.url))),
  );

  assert.deepEqual(
    failures,
    [],
    `Displayed mutable state in runes files must use $state(...).\n${failures.join("\n")}`,
  );
});
