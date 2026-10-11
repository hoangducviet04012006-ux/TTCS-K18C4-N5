"""Sprint 3: Tạo bảng batch_relations và thêm is_overdue cho handovers (T-39, T-56).

Revision ID: 0003_sprint3_batch_relations
Revises: 
Create Date: 2026-10-07 07:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003_sprint3_batch_relations'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tạo bảng batch_relations (T-39)
    op.create_table(
        'batch_relations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('parent_batch_id', sa.Integer(), nullable=False),
        sa.Column('child_batch_id', sa.Integer(), nullable=False),
        sa.Column('transferred_quantity', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('relation_type', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['child_batch_id'], ['batches.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_batch_id'], ['batches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('parent_batch_id', 'child_batch_id', name='uq_parent_child_batch')
    )
    op.create_index('idx_batch_relations_child', 'batch_relations', ['child_batch_id'], unique=False)
    op.create_index('idx_batch_relations_parent', 'batch_relations', ['parent_batch_id'], unique=False)

    # 2. Bổ sung cột is_overdue cho bảng handovers (T-56)
    with op.batch_alter_table('handovers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_overdue', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('handovers', schema=None) as batch_op:
        batch_op.drop_column('is_overdue')

    op.drop_index('idx_batch_relations_parent', table_name='batch_relations')
    op.drop_index('idx_batch_relations_child', table_name='batch_relations')
    op.drop_table('batch_relations')
