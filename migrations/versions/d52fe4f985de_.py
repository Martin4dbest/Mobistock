"""Add nullable date_sold column to order table

Revision ID: d52fe4f985de
Revises: 3256dfb4c7d9
Create Date: 2025-04-18 21:33:11.484741
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd52fe4f985de'
down_revision = '3256dfb4c7d9'
branch_labels = None
depends_on = None


def upgrade():
    # Step 1: Add date_sold as nullable first to avoid errors
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('date_sold', sa.DateTime(), nullable=True))


def downgrade():
    # Reverse the operation
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('date_sold')
