-- 고아 워크플로우 탐지 시 plan_file, runner_id 기준 조회 최적화
CREATE INDEX IF NOT EXISTS ix_workflows_plan_file ON workflows (plan_file);
CREATE INDEX IF NOT EXISTS ix_workflows_runner_id ON workflows (runner_id);
