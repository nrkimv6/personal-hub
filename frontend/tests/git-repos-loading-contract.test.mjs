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

test('git repo detail first render is not blocked by refresh polling', () => {
  const source = read('../src/routes/git-repos/[id]/+page.svelte');
  const loadAll = source.match(/async function loadAll\(\) \{[\s\S]*?\n  \}/)?.[0] ?? '';
  const refreshRepoStatus = source.match(/async function refreshRepoStatus\(\) \{[\s\S]*?\n  \}/)?.[0] ?? '';
  const loadStatus = source.match(/async function loadStatus\(\) \{[\s\S]*?\n  \}/)?.[0] ?? '';

  assert.match(loadAll, /await loadRepo\(\);[\s\S]*loading = false;[\s\S]*await Promise\.all\(\[loadStatus\(\), loadLog\(\), loadOperations\(\)\]\)/);
  assert.doesNotMatch(loadAll, /await gitReposApi\.executeAndPoll\(\s*\(\) => gitReposApi\.refreshRepo\(repoId\)/);
  assert.match(loadAll, /void refreshRepoStatus\(\)/);
  assert.match(refreshRepoStatus, /refreshingStatus = true/);
  assert.match(refreshRepoStatus, /onPending: \(attempt\) =>/);
  assert.match(refreshRepoStatus, /await Promise\.all\(\[loadRepo\(\), loadStatus\(\), loadLog\(\), loadOperations\(\)\]\)/);
  assert.match(loadStatus, /Promise\.allSettled/);
});
