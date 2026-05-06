# fix: root main staged sync recovery

## 선행 계획서와 연결

| 관계 | 계획서 | 근거 |
|---|---|---|
| 직접 선행 | [remote recovery](2026-05-06_fix-remote-ff-only-skill-sync-recovery.md) | 선행 계획이 root local staged 상태를 보존만 하고 닫지 않았다. 이 계획이 닫는다. |
| 방어 선행 | [mirror guard](2026-05-06_fix-block-mirror-direct-edits.md) | 관련 guard 및 재발 방지 계획이다. |

미해소 상태 때문에 후속 복구 계획이 만들어졌다.
