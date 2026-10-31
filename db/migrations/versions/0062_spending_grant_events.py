"""Spending grant events — queryable audit trail for the spending gate.

Every create/revoke/pause/resume/spend/deny on a spending grant is recorded so
a rejected spend is queryable, not just a log line. Race-safe against
``create_all`` via ``IF NOT EXISTS`` (same pattern as 0060/0061).

Revision ID: 0062_spending_grant_events
Revises: 0061_spending_grant
Create Date: 2026-11-01
"""
from alembic import op

revision = "0062_spending_grant_events"
down_revision = "0061_spending_grant"
branch_labels = None
depends_on = None

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS spending_grant_events (
    id INTEGER NOT NULL,
    grant_id VARCHAR(64) NOT NULL,
    owner_identity_id VARCHAR(128) NOT NULL,
    agent_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(24) NOT NULL,
    amount DOUBLE PRECISION,
    reason VARCHAR(256),
    endpoint VARCHAR(64),
    created_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id)
)
"""


def upgrade() -> None:
    op.execute(CREATE_SQL)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_spending_grant_events_grant_id "
        "ON spending_grant_events (grant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_spending_grant_events_created_at "
        "ON spending_grant_events (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS spending_grant_events")
