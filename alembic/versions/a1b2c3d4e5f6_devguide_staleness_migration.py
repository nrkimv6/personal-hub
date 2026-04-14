"""devguide_staleness_migration

Revision ID: a1b2c3d4e5f6
Revises: 23356512e295
Create Date: 2026-04-10 00:00:00.000000

변경 내용:
1. plan_events.plan_record_id — nullable=False → nullable=True (시스템 이벤트 허용)
2. task_schedules.target_type='plan_requirements_sync' → 'devguide_staleness' 업데이트
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '23356512e295'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. plan_events.plan_record_id nullable 변경
    with op.batch_alter_table("plan_events") as batch_op:
        batch_op.alter_column(
            "plan_record_id",
            existing_type=sa.Integer(),
            nullable=True,
        )

    # 2. task_schedules target_type 갱신
    op.execute(
        "UPDATE task_schedules "
        "SET display_name='Dev-Guide 갱신 점검', target_type='devguide_staleness' "
        "WHERE target_type='plan_requirements_sync'"
    )


def downgrade() -> None:
    # task_schedules 복원
    op.execute(
        "UPDATE task_schedules "
        "SET display_name='Plan 요구사항 동기화', target_type='plan_requirements_sync' "
        "WHERE target_type='devguide_staleness'"
    )

    # plan_events.plan_record_id NOT NULL 복원
    # (NULL인 행이 있으면 downgrade 실패할 수 있음)
    with op.batch_alter_table("plan_events") as batch_op:
        batch_op.alter_column(
            "plan_record_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
