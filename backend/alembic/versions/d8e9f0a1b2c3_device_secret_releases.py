"""per-device signing key, assigned releases, fleet default (Rpi-Detector D-020, D-021)

Revision ID: d8e9f0a1b2c3
Revises: c7a1b2d3e4f5
Create Date: 2026-10-24 19:00:00.000000

- `device.config_key`: the configuration signing key derived from the device's
  one secret. NULL for devices created before D-020 — they keep authenticating
  with the old credential but must be re-provisioned before any configuration
  or release can be signed for them.
- `deviceconfig.release`, `deviceconfig.hold`, `deviceconfig.signed_json`: the
  assigned release, the hold switch, and the exact signed document last
  published (what GET /api/devices/config returns byte for byte).
- `fleet_release`: the release a new device is assigned at creation.
- `device_alert.detail`: what a `degraded` or `battery` alert is about, now that
  those alerts are decided here rather than on the device.

Hand-written like the two before it; generate the next one with `make migrate`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401 — see b48e6f1a9d02


revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, None] = 'c7a1b2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('device', sa.Column('config_key', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('deviceconfig', sa.Column('release', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('deviceconfig', sa.Column('hold', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('deviceconfig', sa.Column('signed_json', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('device_alert', sa.Column('detail', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_table(
        'fleet_release',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('release', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('updated_utc', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('fleet_release')
    op.drop_column('device_alert', 'detail')
    op.drop_column('deviceconfig', 'signed_json')
    op.drop_column('deviceconfig', 'hold')
    op.drop_column('deviceconfig', 'release')
    op.drop_column('device', 'config_key')
