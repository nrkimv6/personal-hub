import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const srcRoot = fileURLToPath(new URL("../src", import.meta.url));
const allowedBlockParents = new Set([
  "snippet",
  "if",
  "else if",
  "else",
  "each",
  "then",
  "catch",
  "svelte:fragment",
  "svelte:boundary",
]);
const voidTags = new Set([
  "area",
  "base",
  "br",
  "col",
  "embed",
  "hr",
  "img",
  "input",
  "link",
  "meta",
  "param",
  "source",
  "track",
  "wbr",
]);

function collectSvelteFiles(dir) {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSvelteFiles(path));
    } else if (entry.isFile() && entry.name.endsWith(".svelte")) {
      files.push(path);
    }
  }
  return files;
}

function parentDescription(parent) {
  if (!parent) {
    return "none";
  }
  return `${parent.kind}:${parent.name}`;
}

function isAllowedParent(parent) {
  if (!parent) {
    return false;
  }
  if (parent.kind === "component") {
    return true;
  }
  if (parent.kind === "block") {
    return allowedBlockParents.has(parent.name);
  }
  return false;
}

function closeHtmlTag(stack, tagName) {
  const index = stack.findLastIndex((entry) => entry.kind !== "block" && entry.name === tagName);
  if (index >= 0) {
    stack.splice(index, 1);
  }
}

function closeBlock(stack, blockName) {
  const index = stack.findLastIndex((entry) => entry.kind === "block" && entry.name === blockName);
  if (index >= 0) {
    stack.splice(index, 1);
  }
}

function scanConstPlacement(source, filePath) {
  const failures = [];
  const stack = [];
  const tokenPattern =
    /\{@const\b|\{#(snippet|if|each|await|key)\b|\{:(else if|else|then|catch)\b|\{\/(snippet|if|each|await|key)\}|<\/?([A-Za-z][\w:.-]*)(?:\s[^<>]*)?>/g;
  const lines = source.split(/\r?\n/);

  lines.forEach((line, lineIndex) => {
    tokenPattern.lastIndex = 0;
    for (const match of line.matchAll(tokenPattern)) {
      const token = match[0];

      if (token.startsWith("{@const")) {
        const parent = stack.at(-1);
        if (!isAllowedParent(parent)) {
          failures.push(
            `${filePath}:${lineIndex + 1} invalid {@const} parent ${parentDescription(parent)}: ${line.trim()}`,
          );
        }
        continue;
      }

      if (match[1]) {
        stack.push({ kind: "block", name: match[1] });
        continue;
      }

      if (match[2]) {
        const branchName = match[2];
        const blockIndex = stack.findLastIndex((entry) => entry.kind === "block" && entry.name === "if");
        if (blockIndex >= 0) {
          stack.splice(blockIndex + 1);
        }
        stack.push({ kind: "block", name: branchName });
        continue;
      }

      if (match[3]) {
        closeBlock(stack, match[3]);
        continue;
      }

      if (!match[4]) {
        continue;
      }

      const tagName = match[4];
      if (token.startsWith("</")) {
        closeHtmlTag(stack, tagName);
        continue;
      }

      if (token.endsWith("/>") || voidTags.has(tagName)) {
        continue;
      }

      if (tagName === "svelte:fragment" || tagName === "svelte:boundary") {
        stack.push({ kind: "block", name: tagName });
      } else if (/^[A-Z]/.test(tagName)) {
        stack.push({ kind: "component", name: tagName });
      } else {
        stack.push({ kind: "element", name: tagName });
      }
    }
  });

  return failures;
}

test("Svelte {@const} tags stay under allowed immediate parents", () => {
  const failures = [];
  for (const file of collectSvelteFiles(srcRoot)) {
    const source = readFileSync(file, "utf8");
    const displayPath = relative(srcRoot, file).replaceAll("\\", "/");
    failures.push(...scanConstPlacement(source, displayPath));
  }

  assert.deepEqual(
    failures,
    [],
    `Svelte const tag must be immediate child of each/if/snippet/fragment/component.\n${failures.join("\n")}`,
  );
});
