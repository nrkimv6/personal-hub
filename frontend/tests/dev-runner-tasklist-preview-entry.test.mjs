import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const taskListSource = readFileSync(
  new URL("../src/lib/components/dev-runner/TaskList.svelte", import.meta.url),
  "utf8",
);

const planListSource = readFileSync(
  new URL("../src/lib/components/dev-runner/PlanList.svelte", import.meta.url),
  "utf8",
);

const automationSource = readFileSync(
  new URL("../src/routes/automation/DevRunnerTab.svelte", import.meta.url),
  "utf8",
);

test("task list exposes a plan preview callback from the current runner plan", () => {
  assert.match(taskListSource, /onOpenPlanPreview\?: \(path: string, title\?: string \| null\) => void/);
  assert.match(taskListSource, /onOpenPlanPreview\?\.\(planPath, detail\?\.filename\)/);
  assert.match(taskListSource, />\s*전문 보기\s*</);
});

test("plan list keeps row execution modal selection separate from preview action", () => {
  assert.match(planListSource, /onPlanModalOpen\?: \(plan: DevRunnerPlanFileResponse\) => void/);
  assert.match(planListSource, /onPlanPreviewOpen\?: \(plan: DevRunnerPlanFileResponse\) => void/);
  assert.match(planListSource, /function handlePlanPreview\(e: Event, plan: DevRunnerPlanFileResponse\)/);
  assert.match(planListSource, /e\.stopPropagation\(\);\s*onPlanPreviewOpen\?\.\(plan\);/s);
  assert.match(planListSource, /aria-label="계획서 전문 보기"/);
});

test("automation tab owns preview state and renders desktop and mobile reader surfaces", () => {
  assert.match(automationSource, /import PlanMarkdownPreview/);
  assert.match(automationSource, /let planPreviewOpen = \$state\(false\)/);
  assert.match(automationSource, /function openPlanPreview\(path: string \| null \| undefined, title\?: string \| null\)/);
  assert.match(automationSource, /onOpenPlanPreview=\{openPlanPreview\}/);
  assert.match(automationSource, /onPlanPreviewOpen=\{handlePlanPreviewOpen\}/);
  assert.match(automationSource, /hidden lg:flex w-\[min\(46vw,720px\)\]/);
  assert.match(automationSource, /fixed inset-0 z-\[80\] flex flex-col bg-card lg:hidden/);
  assert.match(automationSource, /planPreviewContextRunnerId !== activeTabId/);
});
