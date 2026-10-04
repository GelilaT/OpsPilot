"""Store HTML email body on email_delivery (separate from JSON ref)."""

from alembic import op
import sqlalchemy as sa

revision = "0008_email_html_body"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_delivery", sa.Column("html_body", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("email_delivery", "html_body")
