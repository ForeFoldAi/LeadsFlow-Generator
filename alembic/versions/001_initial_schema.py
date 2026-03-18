"""Initial schema — scrape_jobs + leads tables

Revision ID: 001
Revises:
Create Date: 2026-01-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── scrape_jobs ───────────────────────────────────────────────────────────
    op.create_table(
        "scrape_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("keyword", sa.String(200), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("max_per_source", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("min_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("country", sa.String(100), nullable=False, server_default="India"),
        sa.Column("total_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    # ── leads ─────────────────────────────────────────────────────────────────
    op.create_table(
        "leads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("scrape_jobs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("category", sa.String(200), nullable=True, server_default=""),
        sa.Column("phone", sa.String(50), nullable=True, server_default=""),
        sa.Column("website", sa.String(500), nullable=True, server_default=""),
        sa.Column("email", sa.String(200), nullable=True, server_default=""),
        sa.Column("address", sa.String(500), nullable=True, server_default=""),
        sa.Column("city", sa.String(100), nullable=True, server_default=""),
        sa.Column("state", sa.String(100), nullable=True, server_default=""),
        sa.Column("zip_code", sa.String(20), nullable=True, server_default=""),
        sa.Column("rating", sa.Float(), nullable=True, server_default="0"),
        sa.Column("reviews", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("hours", sa.String(200), nullable=True, server_default=""),
        sa.Column("sources", sa.Text(), nullable=True, server_default=""),
        sa.Column("source_urls", sa.Text(), nullable=True, server_default=""),
        sa.Column("lead_score", sa.Float(), nullable=True, server_default="0"),
        sa.Column("tier", sa.String(50), nullable=True, server_default=""),
        sa.Column("score_rating", sa.Float(), nullable=True, server_default="0"),
        sa.Column("score_reviews", sa.Float(), nullable=True, server_default="0"),
        sa.Column("score_contact", sa.Float(), nullable=True, server_default="0"),
        sa.Column("score_sources", sa.Float(), nullable=True, server_default="0"),
        sa.Column("score_engagement", sa.Float(), nullable=True, server_default="0"),
        sa.Column("score_profile", sa.Float(), nullable=True, server_default="0"),
        sa.Column("scraped_at", sa.String(30), nullable=True, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.create_index("ix_leads_job_id", "leads", ["job_id"])
    op.create_index("ix_leads_lead_score", "leads", ["lead_score"])
    op.create_index("ix_leads_city", "leads", ["city"])
    op.create_index("ix_leads_tier", "leads", ["tier"])


def downgrade() -> None:
    op.drop_index("ix_leads_tier", "leads")
    op.drop_index("ix_leads_city", "leads")
    op.drop_index("ix_leads_lead_score", "leads")
    op.drop_index("ix_leads_job_id", "leads")
    op.drop_table("leads")
    op.drop_table("scrape_jobs")
