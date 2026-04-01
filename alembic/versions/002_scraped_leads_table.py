"""Add scraped_leads table (Generator's dedicated leads table)

Revision ID: 002
Revises: 001
Create Date: 2026-03-29 00:00:00.000000

NOTE: The shared DB already has a 'leads' table belonging to the CRM backend.
      The Generator uses 'scraped_leads' to avoid collision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scraped_leads",
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
        sa.Column("enriched_from", sa.String(50), nullable=True, server_default=""),
        sa.Column("confidence_score", sa.Float(), nullable=True, server_default="0"),
        sa.Column("scraped_at", sa.String(30), nullable=True, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index("ix_scraped_leads_job_id", "scraped_leads", ["job_id"])
    op.create_index("ix_scraped_leads_lead_score", "scraped_leads", ["lead_score"])
    op.create_index("ix_scraped_leads_city", "scraped_leads", ["city"])
    op.create_index("ix_scraped_leads_tier", "scraped_leads", ["tier"])


def downgrade() -> None:
    op.drop_index("ix_scraped_leads_tier", "scraped_leads")
    op.drop_index("ix_scraped_leads_city", "scraped_leads")
    op.drop_index("ix_scraped_leads_lead_score", "scraped_leads")
    op.drop_index("ix_scraped_leads_job_id", "scraped_leads")
    op.drop_table("scraped_leads")
