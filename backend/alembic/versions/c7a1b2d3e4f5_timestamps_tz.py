"""offset-aware timestamps on the four columns that were still naive

Revision ID: c7a1b2d3e4f5
Revises: b48e6f1a9d02
Create Date: 2026-10-24 17:30:00.000000

`user.created_at`, `site.created_at`, `device.last_seen` and
`deviceconfig.updated_utc` were plain `DateTime()` while every value written to
them is offset-aware UTC. Postgres silently dropped the offset, so the API
serialised them without one and a browser in Chile read them as local time
(review BE-07c, 2026-10-24). Everything else in the schema was already
`timestamptz`; this brings the stragglers in line with `models._TZ_DATETIME`.

Postgres only. SQLite has no timezone type and the test suite builds its schema
with `create_all`, so there is nothing to alter there. Hand-written, like
`9c2ab4e17d05` and `b48e6f1a9d02`; generate the next one with `make migrate`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401 — see b48e6f1a9d02 for why this import is here


# revision identifiers, used by Alembic.
revision: str = 'c7a1b2d3e4f5'
down_revision: Union[str, None] = 'b48e6f1a9d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("user", "created_at", False),
    ("site", "created_at", False),
    ("device", "last_seen", True),
    ("deviceconfig", "updated_utc", False),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column, nullable in _COLUMNS:
        # Stored values are UTC wall-clock without offset; declare them as such.
        op.alter_column(table, column,
                        existing_type=sa.DateTime(),
                        type_=sa.DateTime(timezone=True),
                        existing_nullable=nullable,
                        postgresql_using=f"{column} AT TIME ZONE 'UTC'")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column, nullable in _COLUMNS:
        op.alter_column(table, column,
                        existing_type=sa.DateTime(timezone=True),
                        type_=sa.DateTime(),
                        existing_nullable=nullable,
                        postgresql_using=f"{column} AT TIME ZONE 'UTC'")
