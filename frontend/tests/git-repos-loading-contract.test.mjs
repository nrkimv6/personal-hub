import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('executeAndPoll validates task id and failed task result contract', () => {
  const source = read('../src/lib/api/gitRepos.ts');

  assert.match(source, /onPending\?: \(attempt: number\) => void/);
  assert.match(source, /if \(!taskId\)/);
  assert.match(source, /result\.status === 'failed'/);
  assert.match(source, /result\.result\?\.stderr/);
  assert.match(source, /result\.result\?\.stdout/);
  assert.match(source, /options\?\.onPending\?\.\(i \+ 1\)/);
});
