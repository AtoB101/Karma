"""Data-API commerce: 主体资质认证 + 技能上架 + 按次计费（小额高频，到阈值结算）。

三个层次各一张主表加两张流水表：

* ``entity_verifications`` —— 谁在卖（营业执照 / 法定代表人 / 官网控制权）。
  资质原件只存密文包 + 摘要，与 ``identity_verifications`` 同一套加密约定。
* ``skills`` —— 卖什么、单价多少、累计到多少才出账（``settlement_threshold_usdc``）。
  上架必须由本人在册钱包签名，所以签名、签名者、认证域都落库。
* ``usage_meters`` / ``usage_charges`` / ``usage_settlements`` —— 记一次调用（幂等）、
  按「付款方 × 技能」累计、到阈值出账、再由链上非托管授权划转。

全部为新表，没有改动任何既有列，老数据与老 agent 行为不受影响。

Revision ID: 0045_data_api_commerce
Revises: 0044_escrow_capacity_mirror
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0045_data_api_commerce"
down_revision = "0044_escrow_capacity_mirror"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_verifications",
        sa.Column("identity_id", sa.String(128), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="none"),
        sa.Column("subject_type", sa.String(16), nullable=False, server_default="business"),
        sa.Column("legal_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("registration_no", sa.String(64), nullable=False, server_default=""),
        sa.Column("jurisdiction", sa.String(64), nullable=False, server_default=""),
        sa.Column("legal_rep", sa.String(120), nullable=False, server_default=""),
        sa.Column("official_domain", sa.String(255), nullable=False, server_default=""),
        sa.Column("contact_email", sa.String(200), nullable=False, server_default=""),
        sa.Column("service_category", sa.String(64), nullable=False, server_default=""),
        sa.Column("service_scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("certifications", sa.JSON(), nullable=True),
        sa.Column("doc_digest", sa.String(128), nullable=True),
        sa.Column("package_digest", sa.String(128), nullable=True),
        sa.Column("package_cipher", sa.Text(), nullable=True),
        sa.Column("encryption", sa.JSON(), nullable=True),
        sa.Column("extracted", sa.JSON(), nullable=True),
        sa.Column("website_token", sa.String(128), nullable=True),
        sa.Column("website_challenge_at", sa.DateTime(), nullable=True),
        sa.Column("website_verified_at", sa.DateTime(), nullable=True),
        sa.Column("website_digest", sa.String(128), nullable=True),
        sa.Column("reviewer_identity_id", sa.String(128), nullable=True),
        sa.Column("review_note", sa.String(2000), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_entity_verifications_official_domain", "entity_verifications", ["official_domain"])
    op.create_index("ix_entity_verifications_status", "entity_verifications", ["status"])

    op.create_table(
        "skills",
        sa.Column("skill_id", sa.String(64), primary_key=True),
        sa.Column("owner_identity_id", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(64), nullable=False, server_default="data_api"),
        sa.Column("summary", sa.String(300), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("endpoint_url", sa.String(500), nullable=False),
        sa.Column("method", sa.String(8), nullable=False, server_default="POST"),
        sa.Column("unit", sa.String(32), nullable=False, server_default="call"),
        sa.Column("unit_price_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("settlement_threshold_usdc", sa.Float(), nullable=False, server_default="1"),
        sa.Column("default_cap_usdc", sa.Float(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("manifest_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("publisher_signature", sa.String(200), nullable=True),
        sa.Column("publisher_wallet", sa.String(128), nullable=True),
        sa.Column("verified_domain", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("paused_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("slug", name="uq_skills_slug"),
    )
    op.create_index("ix_skills_owner_identity_id", "skills", ["owner_identity_id"])
    op.create_index("ix_skills_status", "skills", ["status"])

    op.create_table(
        "usage_meters",
        sa.Column("meter_id", sa.String(64), primary_key=True),
        sa.Column("skill_id", sa.String(64), nullable=False),
        sa.Column("payer_identity_id", sa.String(128), nullable=False),
        sa.Column("provider_identity_id", sa.String(128), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accrued_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("billed_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("settled_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("threshold_usdc", sa.Float(), nullable=False, server_default="1"),
        sa.Column("cap_usdc", sa.Float(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("skill_id", "payer_identity_id", name="uq_usage_meter_skill_payer"),
    )
    op.create_index("ix_usage_meters_skill_id", "usage_meters", ["skill_id"])
    op.create_index("ix_usage_meters_payer_identity_id", "usage_meters", ["payer_identity_id"])
    op.create_index("ix_usage_meters_provider_identity_id", "usage_meters", ["provider_identity_id"])

    op.create_table(
        "usage_charges",
        sa.Column("charge_id", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.String(80), nullable=False),
        sa.Column("skill_id", sa.String(64), nullable=False),
        sa.Column("payer_identity_id", sa.String(128), nullable=False),
        sa.Column("provider_identity_id", sa.String(128), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_price_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("amount_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("settlement_id", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("skill_id", "request_id", name="uq_usage_charge_skill_request"),
    )
    op.create_index("ix_usage_charges_skill_id", "usage_charges", ["skill_id"])
    op.create_index("ix_usage_charges_payer_identity_id", "usage_charges", ["payer_identity_id"])
    op.create_index("ix_usage_charges_settlement_id", "usage_charges", ["settlement_id"])

    op.create_table(
        "usage_settlements",
        sa.Column("settlement_id", sa.String(64), primary_key=True),
        sa.Column("skill_id", sa.String(64), nullable=False),
        sa.Column("payer_identity_id", sa.String(128), nullable=False),
        sa.Column("provider_identity_id", sa.String(128), nullable=False),
        sa.Column("amount_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stake_usdc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("mode", sa.String(24), nullable=False, server_default="escrow_allowance"),
        sa.Column("digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("escrow_binding_id", sa.String(64), nullable=True),
        sa.Column("tx_hash", sa.String(80), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_usage_settlements_skill_id", "usage_settlements", ["skill_id"])
    op.create_index("ix_usage_settlements_payer_identity_id", "usage_settlements", ["payer_identity_id"])
    op.create_index("ix_usage_settlements_provider_identity_id", "usage_settlements", ["provider_identity_id"])
    op.create_index("ix_usage_settlements_status", "usage_settlements", ["status"])


def downgrade() -> None:
    op.drop_index("ix_usage_settlements_status", table_name="usage_settlements")
    op.drop_index("ix_usage_settlements_provider_identity_id", table_name="usage_settlements")
    op.drop_index("ix_usage_settlements_payer_identity_id", table_name="usage_settlements")
    op.drop_index("ix_usage_settlements_skill_id", table_name="usage_settlements")
    op.drop_table("usage_settlements")

    op.drop_index("ix_usage_charges_settlement_id", table_name="usage_charges")
    op.drop_index("ix_usage_charges_payer_identity_id", table_name="usage_charges")
    op.drop_index("ix_usage_charges_skill_id", table_name="usage_charges")
    op.drop_table("usage_charges")

    op.drop_index("ix_usage_meters_provider_identity_id", table_name="usage_meters")
    op.drop_index("ix_usage_meters_payer_identity_id", table_name="usage_meters")
    op.drop_index("ix_usage_meters_skill_id", table_name="usage_meters")
    op.drop_table("usage_meters")

    op.drop_index("ix_skills_status", table_name="skills")
    op.drop_index("ix_skills_owner_identity_id", table_name="skills")
    op.drop_table("skills")

    op.drop_index("ix_entity_verifications_status", table_name="entity_verifications")
    op.drop_index("ix_entity_verifications_official_domain", table_name="entity_verifications")
    op.drop_table("entity_verifications")