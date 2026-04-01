"""Add scrape_jobs and generated_leads tables

Revision ID: 001
Revises:
Create Date: 2026-03-27 00:00:00.000000

Tables created:
  - scrape_jobs        : tracks each lead generation job, scoped to user + admin
  - generated_leads    : stores every scraped lead with company-level duplicate flag

Duplicate detection logic (applied in lead_engine.py at runtime):
  - admin_user_id is resolved from user_permissions.parent_user_id
  - If no parent exists the requesting user IS the admin
  - A lead is marked is_duplicate=true if phone_number OR (name+city) already
    exists in the leads table for any user within the same company (same admin)
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
    # Tracks every generation request.
    # user_id      → the user who triggered the job (FK to users)
    # admin_user_id → resolved company admin (parent_user_id from user_permissions)
    op.create_table(
        "scrape_jobs",
        sa.Column("id", sa.String(255), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("admin_user_id", sa.String(255), nullable=True),
        sa.Column("keyword", sa.String(200), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("max_per_source", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("min_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("country", sa.String(100), nullable=False, server_default="India"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("total_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_scrape_jobs_user_id", "scrape_jobs", ["user_id"])
    op.create_index("ix_scrape_jobs_admin_user_id", "scrape_jobs", ["admin_user_id"])
    op.create_index("ix_scrape_jobs_status", "scrape_jobs", ["status"])
    op.create_index("ix_scrape_jobs_created_at", "scrape_jobs", ["created_at"])

    # ── generated_leads ───────────────────────────────────────────────────────
    # Stores every lead the scraper produces.
    # is_duplicate         → true  if this lead already exists in the company's leads table
    # duplicate_of_lead_id → points to leads.id of the matched CRM lead (if any)
    op.create_table(
        "generated_leads",
        sa.Column("id", sa.String(255), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", sa.String(255), sa.ForeignKey("scrape_jobs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("admin_user_id", sa.String(255), nullable=True),  # company scope key

        # ── Lead identity ─────────────────────────────────────────────────────
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("phone_number", sa.String(50), nullable=True, server_default=""),
        sa.Column("email", sa.String(255), nullable=True, server_default=""),
        sa.Column("city", sa.String(255), nullable=True, server_default=""),
        sa.Column("state", sa.String(255), nullable=True, server_default=""),
        sa.Column("country", sa.String(255), nullable=True, server_default=""),
        sa.Column("pincode", sa.String(20), nullable=True, server_default=""),
        sa.Column("address", sa.Text(), nullable=True, server_default=""),
        sa.Column("company_name", sa.String(255), nullable=True, server_default=""),
        sa.Column("website", sa.String(500), nullable=True, server_default=""),
        sa.Column("category", sa.String(200), nullable=True, server_default=""),

        # ── Scores ───────────────────────────────────────────────────────────
        sa.Column("rating", sa.Float(), nullable=True, server_default="0"),
        sa.Column("reviews", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("lead_score", sa.Float(), nullable=True, server_default="0"),
        sa.Column("tier", sa.String(50), nullable=True, server_default=""),
        sa.Column("sources", sa.Text(), nullable=True, server_default=""),

        # ── Duplicate detection ───────────────────────────────────────────────
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("duplicate_of_lead_id", sa.String(255), nullable=True),  # leads.id match

        # ── Meta ─────────────────────────────────────────────────────────────
        sa.Column("scraped_at", sa.String(30), nullable=True, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_gen_leads_job_id", "generated_leads", ["job_id"])
    op.create_index("ix_gen_leads_user_id", "generated_leads", ["user_id"])
    op.create_index("ix_gen_leads_admin_user_id", "generated_leads", ["admin_user_id"])
    op.create_index("ix_gen_leads_is_duplicate", "generated_leads", ["is_duplicate"])
    op.create_index("ix_gen_leads_phone_number", "generated_leads", ["phone_number"])
    op.create_index("ix_gen_leads_lead_score", "generated_leads", ["lead_score"])
    op.create_index("ix_gen_leads_created_at", "generated_leads", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_gen_leads_created_at", "generated_leads")
    op.drop_index("ix_gen_leads_lead_score", "generated_leads")
    op.drop_index("ix_gen_leads_phone_number", "generated_leads")
    op.drop_index("ix_gen_leads_is_duplicate", "generated_leads")
    op.drop_index("ix_gen_leads_admin_user_id", "generated_leads")
    op.drop_index("ix_gen_leads_user_id", "generated_leads")
    op.drop_index("ix_gen_leads_job_id", "generated_leads")
    op.drop_table("generated_leads")

    op.drop_index("ix_scrape_jobs_created_at", "scrape_jobs")
    op.drop_index("ix_scrape_jobs_status", "scrape_jobs")
    op.drop_index("ix_scrape_jobs_admin_user_id", "scrape_jobs")
    op.drop_index("ix_scrape_jobs_user_id", "scrape_jobs")
    op.drop_table("scrape_jobs")
