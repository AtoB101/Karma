"""Spending grants: owner-signed budgeted authorization for agents.

Adds the ``spending_grants`` table. The owner approves the grant with a wallet
signature over canonical terms (total limit, per-transaction limit, currency,
expiry, purpose scope, agent public key binding); the signature and signed
message are stored on the row so the grant is self-certifying. Renewal is not
allowed by default — a new grant is a new signed record.

``create_all`` and alembic both may create this table (see 0060), so the DDL
uses ``IF NOT EXISTS`` to stay race-safe on deploy.

Revision ID: 0061_spending_grant
Revises: 0070_settlement_reversals
Create Date: 2026-11-01
"""
from alembic import op

revision = "0061_spending_grant"
down_revision = "0070_settlement_reversals"
branch_labels = None
depends_on = None

#: 列名/类型与 ``db/models/orm.py`` 的 ``SpendingGrantModel`` 逐字对应。
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS spending_grants (
    grant_id VARCHAR(64) NOT NULL,
    owner_identity_id VARCHAR(128) NOT NULL,
    owner_wallet_address VARCHAR(42) NOT NULL,
    agent_id VARCHAR(128) NOT NULL,
    agent_public_key VARCHAR(256),
    currency VARCHAR(16) NOT NULL,
    token_address VARCHAR(42),
    total_limit DOUBLE PRECISION NOT NULL,
    per_tx_limit DOUBLE PRECISION NOT NULL,
    used_amount DOUBLE PRECISION NOT NULL,
    purpose_scope JSON NOT NULL,
    status VARCHAR(16) NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE,
    nonce VARCHAR(64) NOT NULL,
    signature VARCHAR(256) NOT NULL,
    signed_message TEXT NOT NULL,
    last_used_at TIMESTAMP WITHOUT TIME ZONE,
    last_denied_reason VARCHAR(256),
    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    revoke_reason VARCHAR(256),
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (grant_id)
)
"""


def upgrade() -> None:
    op.execute(CREATE_SQL)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_spending_grants_owner_identity_id "
        "ON spending_grants (owner_identity_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_spending_grants_agent_id "
        "ON spending_grants (agent_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS spending_grants")
