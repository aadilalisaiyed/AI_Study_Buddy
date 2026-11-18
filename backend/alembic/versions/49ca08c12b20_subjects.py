"""Add user-owned subjects and immutable quiz subject attribution."""
import sqlalchemy as sa
from alembic import op

revision = "49ca08c12b20"
down_revision = "39da08c12b10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subjects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("normalized", sa.String(240), nullable=False),
        sa.UniqueConstraint("user_id", "normalized", name="uq_subject_owner_name"),
    )
    op.add_column("documents", sa.Column("subject_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_document_subject", "documents", "subjects", ["subject_id"], ["id"], ondelete="SET NULL")
    op.add_column("quizzes", sa.Column("subject_label", sa.String(80), nullable=True))
    op.add_column("quizzes", sa.Column("subject_key", sa.String(240), nullable=True))


def downgrade():
    op.drop_column("quizzes", "subject_key")
    op.drop_column("quizzes", "subject_label")
    op.drop_constraint("fk_document_subject", "documents", type_="foreignkey")
    op.drop_column("documents", "subject_id")
    op.drop_table("subjects")
