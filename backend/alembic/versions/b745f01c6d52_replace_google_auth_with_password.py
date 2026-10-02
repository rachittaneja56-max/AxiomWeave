"""replace Google identity with username/password authentication

Revision ID: b745f01c6d52
Revises: f0ba32d0f7a1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b745f01c6d52"
down_revision: str | None = "f0ba32d0f7a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.add_column("users", sa.Column("username", sa.String(length=64), nullable=True))
        op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
        op.execute(
            sa.text(
                "UPDATE users "
                "SET username = 'legacy-migrated-' || CAST(id AS VARCHAR), "
                "password_hash = '!disabled-legacy-google!'"
            )
        )
        op.alter_column("users", "username", existing_type=sa.String(length=64), nullable=False)
        op.alter_column(
            "users", "password_hash", existing_type=sa.String(length=255), nullable=False
        )
        op.create_unique_constraint("uq_users_username", "users", ["username"])
        op.drop_column("users", "google_subject")
    else:
        op.execute(
            "CREATE TABLE users_new ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "username VARCHAR(64) NOT NULL UNIQUE, "
            "password_hash VARCHAR(255) NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
        op.execute(
            "INSERT INTO users_new (id, username, password_hash, created_at) "
            "SELECT id, 'legacy-migrated-' || id, '!disabled-legacy-google!', created_at FROM users"
        )
        op.drop_table("users")
        op.rename_table("users_new", "users")
    op.create_table(
        "login_throttles",
        sa.Column("login_key_digest", sa.String(64), primary_key=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("login_throttles")
    op.execute(
        "CREATE TABLE users_old ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "google_subject VARCHAR(255) NOT NULL UNIQUE, "
        "created_at DATETIME NOT NULL)"
    )
    op.execute(
        "INSERT INTO users_old (id, google_subject, created_at) "
        "SELECT id, 'legacy-disabled-' || id, created_at FROM users"
    )
    op.drop_table("users")
    op.rename_table("users_old", "users")
