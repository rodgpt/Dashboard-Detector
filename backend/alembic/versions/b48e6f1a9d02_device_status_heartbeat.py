"""device status heartbeat

Revision ID: b48e6f1a9d02
Revises: 9c2ab4e17d05
Create Date: 2026-09-23 15:00:00.000000

Adds `device_status` (current snapshot, upserted per heartbeat) and
`device_status_history` (append-only) — see `DATA-CONTRACT.md`,
**Device heartbeat**, and `core/models.py`.

Written by hand, matching `9c2ab4e17d05`'s note: generate the next revision
properly with `make migrate` rather than editing this one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
# SQLModel autogenerate emits sqlmodel.sql.sqltypes.* for str columns but does
# not import the module. Without this line every generated migration fails
# with NameError at upgrade time.
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b48e6f1a9d02'
down_revision: Union[str, None] = '9c2ab4e17d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'device_status',
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('reported_last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['device.id']),
        sa.PrimaryKeyConstraint('device_id'),
    )
    op.create_table(
        'device_status_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('reported_last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['device.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_device_status_history_device_id'),
                    'device_status_history', ['device_id'], unique=False)
    op.create_index('ix_device_status_history_device_received',
                    'device_status_history', ['device_id', 'received_utc'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_device_status_history_device_received',
                  table_name='device_status_history')
    op.drop_index(op.f('ix_device_status_history_device_id'),
                  table_name='device_status_history')
    op.drop_table('device_status_history')
    op.drop_table('device_status')
