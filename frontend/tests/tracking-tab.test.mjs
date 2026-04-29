import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  TRACKING_FILTERS,
  buildTrackingPayload,
  getTrackingStatusClass,
  getTrackingStatusLabel,
  sortTrackingItems,
} from "../src/lib/utils/tracking.js";

test("Automation page exposes the Tracking top-level tab", () => {
  const pageSource = readFileSync(new URL("../src/routes/automation/+page.svelte", import.meta.url), "utf8");
  assert.match(pageSource, /TrackingTab/);
  assert.match(pageSource, /id: 'tracking'/);
  assert.match(pageSource, /label: 'Tracking'/);
});

test("Tracking tab renders expected filter set", () => {
  assert.deepEqual(TRACKING_FILTERS, ["all", "overdue", "ready", "upcoming", "done"]);
});

test("Tracking status badges expose Korean labels and variant classes", () => {
  assert.equal(getTrackingStatusLabel("overdue"), "지연");
  assert.equal(getTrackingStatusLabel("ready"), "준비됨");
  assert.equal(getTrackingStatusLabel("upcoming"), "예정");
  assert.equal(getTrackingStatusLabel("done"), "완료");
  assert.match(getTrackingStatusClass("overdue"), /red/);
  assert.match(getTrackingStatusClass("upcoming"), /blue/);
});

test("Tracking create payload trims title and keeps one date boundary", () => {
  const payload = buildTrackingPayload({
    title: "  배포 검토  ",
    description: "",
    start_at: "",
    due_at: "2026-04-30T10:00",
  });

  assert.deepEqual(payload, {
    title: "배포 검토",
    description: null,
    start_at: null,
    due_at: "2026-04-30T10:00",
  });
});

test("Tracking create payload requires title and start or due", () => {
  assert.throws(
    () => buildTrackingPayload({ title: "", description: "", start_at: "", due_at: "" }),
    /제목/
  );
  assert.throws(
    () => buildTrackingPayload({ title: "검토", description: "", start_at: "", due_at: "" }),
    /시작가능일 또는 마감기한/
  );
});

test("Tracking local updates keep default sort order", () => {
  const sorted = sortTrackingItems([
    { title: "Done old", status: "done", completed_at: "2026-04-28T09:00:00" },
    { title: "Upcoming", status: "upcoming", start_at: "2026-05-01T09:00:00" },
    { title: "Ready", status: "ready", due_at: "2026-04-30T09:00:00" },
    { title: "Overdue", status: "overdue", due_at: "2026-04-28T09:00:00" },
    { title: "Done new", status: "done", completed_at: "2026-04-29T09:00:00" },
  ]);

  assert.deepEqual(sorted.map((item) => item.title), [
    "Overdue",
    "Ready",
    "Upcoming",
    "Done new",
    "Done old",
  ]);
});
