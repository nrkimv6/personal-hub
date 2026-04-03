# dev_runner test notes

## Targeted regression set

When changing runtime helper dedupe or Redis mock strictness, run:

```powershell
python -m pytest `
  tests/dev_runner/test_dr_runtime_utils.py `
  tests/dev_runner/test_noise_filter_76.py `
  tests/dev_runner/test_v2_merge_fallback.py `
  tests/dev_runner/test_stream_output_merge.py `
  tests/dev_runner/test_v2_merge_gate.py -q
```

Equivalent shortcut:

```powershell
.\scripts\test.ps1 -DevRunnerRegression
```

## Strict Redis mock rule

- Use `strict_redis_mock` fixture from `tests/dev_runner/conftest.py` for Redis `MagicMock`.
- If a custom Redis mock is needed, start from `attach_default_redis_behaviors(...)`.
- Add `assert_no_magicmock_leak(...)` checks where branch conditions depend on `redis.get(...)`.
