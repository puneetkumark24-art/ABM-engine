"""campaign workspace authoring fields, brands and revisions

Revision ID: w0e2f4a6b8d0
Revises: v9d1f3a5b7c9
"""
from alembic import op
import sqlalchemy as sa
revision="w0e2f4a6b8d0"; down_revision="v9d1f3a5b7c9"; branch_labels=None; depends_on=None
def upgrade():
    bind=op.get_bind(); cols={c["name"] for c in sa.inspect(bind).get_columns("email_campaigns")}
    for name,col in [("content_blocks",sa.JSON()),("brand_profile_id",sa.String(36)),("approval_status",sa.String()),("version",sa.Integer()),("updated_at",sa.DateTime())]:
        if name not in cols: op.add_column("email_campaigns",sa.Column(name,col,nullable=True))
    if "email_brand_profiles" not in sa.inspect(bind).get_table_names():
        op.create_table("email_brand_profiles",sa.Column("id",sa.String(36),primary_key=True),sa.Column("name",sa.String(),nullable=False,unique=True),sa.Column("logo_url",sa.String()),sa.Column("primary_color",sa.String(16)),sa.Column("accent_color",sa.String(16)),sa.Column("font_family",sa.String()),sa.Column("footer_html",sa.Text()),sa.Column("sender_name",sa.String()),sa.Column("reply_to",sa.String()),sa.Column("created_at",sa.DateTime()))
    if "email_campaign_revisions" not in sa.inspect(bind).get_table_names():
        op.create_table("email_campaign_revisions",sa.Column("id",sa.String(36),primary_key=True),sa.Column("campaign_id",sa.String(36),nullable=False),sa.Column("version",sa.Integer(),nullable=False),sa.Column("snapshot",sa.JSON(),nullable=False),sa.Column("actor",sa.String()),sa.Column("note",sa.String()),sa.Column("created_at",sa.DateTime()),sa.UniqueConstraint("campaign_id","version"))
    _ensure_brand_profile_fk(bind)


def _ensure_brand_profile_fk(bind) -> None:
    """Add email_campaigns.brand_profile_id -> email_brand_profiles.id HERE.

    The constraint cannot be declared on the model: `email_campaigns` is built
    by the historical migration d4e8b1c5a7f9 from models_ext.ALL_TABLES, which
    runs long before this migration creates `email_brand_profiles`. Declaring
    it there made `alembic upgrade head` fail on a FRESH database with
    `relation "email_brand_profiles" does not exist`, while passing on an
    already-migrated one (checkfirst=True skips the existing table) -- so it
    would only ever have surfaced on a new deployment.

    Adding it here keeps the database enforcing referential integrity while
    respecting the order the tables actually come into existence. PostgreSQL
    only: SQLite cannot add a constraint to an existing table, and the dev
    path does not need it.
    """
    if bind.dialect.name != "postgresql":
        return
    existing = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("email_campaigns")}
    if "fk_email_campaigns_brand_profile" in existing:
        return
    op.create_foreign_key("fk_email_campaigns_brand_profile", "email_campaigns",
                          "email_brand_profiles", ["brand_profile_id"], ["id"],
                          ondelete="SET NULL")


def downgrade():
    bind_fk = op.get_bind()
    if bind_fk.dialect.name == "postgresql":
        existing = {fk["name"] for fk in sa.inspect(bind_fk).get_foreign_keys("email_campaigns")}
        if "fk_email_campaigns_brand_profile" in existing:
            op.drop_constraint("fk_email_campaigns_brand_profile", "email_campaigns",
                               type_="foreignkey")
    bind=op.get_bind(); cols={c["name"] for c in sa.inspect(bind).get_columns("email_campaigns")}
    # SQLite must rebuild the table to remove a column participating in a
    # foreign-key definition. batch_alter_table handles that safely and is
    # also valid for PostgreSQL schema-clone rehearsals.
    with op.batch_alter_table("email_campaigns") as batch:
        for n in ("updated_at","version","approval_status","brand_profile_id","content_blocks"):
            if n in cols: batch.drop_column(n)
    op.drop_table("email_campaign_revisions"); op.drop_table("email_brand_profiles")
