"""mp4_gif_tasks: add width, overwrite_mode, download_filename columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-04

MP4→GIF 옵션 확장(width, overwrite_mode, download_filename) 컬럼 추가.
init_extra_tables의 _add_col 헬퍼로도 처리되지만, 명시적 마이그레이션을 남긴다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # mp4_gif_tasks 테이블에 새 컬럼 추가 (이미 있으면 무시)
    with op.batch_alter_table("mp4_gif_tasks") as batch_op:
        batch_op.add_column(
            sa.Column("width", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "overwrite_mode",
                sa.String(20),
                nullable=False,
                server_default="overwrite",
            )
        )
        batch_op.add_column(
            sa.Column("download_filename", sa.String(255), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("mp4_gif_tasks") as batch_op:
        batch_op.drop_column("download_filename")
        batch_op.drop_column("overwrite_mode")
        batch_op.drop_column("width")
