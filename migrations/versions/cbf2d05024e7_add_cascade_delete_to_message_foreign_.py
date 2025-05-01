"""Add cascade delete to Message foreign keys

Revision ID: cbf2d05024e7
Revises: 09d31b4ded17
Create Date: 2025-05-01 21:12:21.710360
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cbf2d05024e7'
down_revision = '09d31b4ded17'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('message', schema=None) as batch_op:
        # Drop existing foreign keys
        batch_op.drop_constraint('message_sender_id_fkey', type_='foreignkey')
        batch_op.drop_constraint('message_receiver_id_fkey', type_='foreignkey')

        # Create new foreign keys with ON DELETE CASCADE
        batch_op.create_foreign_key(
            'message_sender_id_fkey', 'user',
            ['sender_id'], ['id'], ondelete='CASCADE'
        )
        batch_op.create_foreign_key(
            'message_receiver_id_fkey', 'user',
            ['receiver_id'], ['id'], ondelete='CASCADE'
        )

def downgrade():
    with op.batch_alter_table('message', schema=None) as batch_op:
        # Drop cascading foreign keys
        batch_op.drop_constraint('message_sender_id_fkey', type_='foreignkey')
        batch_op.drop_constraint('message_receiver_id_fkey', type_='foreignkey')

        # Recreate original (non-cascading) foreign keys
        batch_op.create_foreign_key(
            'message_sender_id_fkey', 'user',
            ['sender_id'], ['id']
        )
        batch_op.create_foreign_key(
            'message_receiver_id_fkey', 'user',
            ['receiver_id'], ['id']
        )
