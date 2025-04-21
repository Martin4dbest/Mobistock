"""Added unique constraint on product identification per location

Revision ID: ecd56cbef5e8
Revises: 3e5b8873b591
Create Date: 2025-04-22 00:52:44.854977
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'ecd56cbef5e8'
down_revision = '3e5b8873b591'
branch_labels = None
depends_on = None

def upgrade():
    # Drop foreign key constraints first
    op.drop_constraint('inventory_product_id_fkey', 'inventory', type_='foreignkey')  # Drop FK constraint from inventory
    op.drop_constraint('order_product_id_fkey', 'order', type_='foreignkey')  # Drop FK constraint from order

    # Now you can safely drop the tables
    op.drop_table('product')
    op.drop_table('order')
    op.drop_table('inventory')
    op.drop_table('user')

def downgrade():
    # Recreate the tables and foreign key constraints
    op.create_table('inventory',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('product_id', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('quantity_in_stock', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('quantity_sold', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('in_stock', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('seller_id', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], name='inventory_product_id_fkey'),
        sa.ForeignKeyConstraint(['seller_id'], ['user.id'], name='inventory_seller_id_fkey'),
        sa.PrimaryKeyConstraint('id', name='inventory_pkey')
    )

    op.create_table('order',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('product_id', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('quantity', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('status', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('selling_price', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
        sa.Column('amount', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
        sa.Column('in_stock', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('date_sold', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], name='order_product_id_fkey'),
        sa.PrimaryKeyConstraint('id', name='order_pkey')
    )

    op.create_table('product',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('name', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('price', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
        sa.Column('selling_price', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
        sa.Column('identification_number', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('in_stock', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('location', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint('id', name='product_pkey'),
        sa.UniqueConstraint('identification_number', 'location', name='uq_product_identification_per_location')
    )

    op.create_table('user',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('username', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('password', sa.VARCHAR(length=256), autoincrement=False, nullable=False),
        sa.Column('role', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('location', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.PrimaryKeyConstraint('id', name='user_pkey'),
        sa.UniqueConstraint('username', name='user_username_key')
    )
