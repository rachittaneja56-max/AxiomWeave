"""revoke sessions created before the password-auth cutover

Revision ID: c2a7e18f4d91
Revises: b745f01c6d52
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2a7e18f4d91"
down_revision: str | None = "b745f01c6d52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE revoked_at IS NULL")


def downgrade() -> None:
    # Session revocation is intentionally irreversible. Restoring previously valid
    # authentication state after a downgrade would be unsafe and inaccurate.
    pass
