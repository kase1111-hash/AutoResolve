"""Initial database schema for AutoResolve.

Revision ID: 001
Revises: None
Create Date: 2026-01-10 00:00:01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create monitored_repos table
    op.create_table(
        'monitored_repos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repo_full_name', sa.String(255), nullable=False),
        sa.Column('installation_id', sa.BigInteger(), nullable=True),
        sa.Column('webhook_id', sa.BigInteger(), nullable=True),
        sa.Column('webhook_secret', sa.String(255), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('settings', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repo_full_name')
    )
    op.create_index('idx_repos_enabled', 'monitored_repos', ['enabled'])

    # Create issues table
    op.create_table(
        'issues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('queue_id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('github_issue_id', sa.Integer(), nullable=False),
        sa.Column('repo_full_name', sa.String(255), nullable=False),
        sa.Column('repo_url', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('labels', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('author', sa.String(100), nullable=True),
        sa.Column('error_type', sa.String(100), nullable=True),
        sa.Column('error_signature', sa.Text(), nullable=True),
        sa.Column('github_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('queued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('queue_id'),
        sa.UniqueConstraint('repo_full_name', 'github_issue_id', name='uq_issue_repo')
    )
    op.create_index('idx_issues_status', 'issues', ['status'])
    op.create_index('idx_issues_repo', 'issues', ['repo_full_name'])
    op.create_index('idx_issues_priority', 'issues', ['priority'])

    # Create validations table
    op.create_table(
        'validations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('issue_id', sa.Integer(), nullable=False),
        sa.Column('valid', sa.Boolean(), nullable=False),
        sa.Column('validity_status', sa.String(50), nullable=True),
        sa.Column('match_score', sa.Float(), nullable=True),
        sa.Column('error_signature', sa.Text(), nullable=True),
        sa.Column('issue_context', postgresql.JSONB(), nullable=True),
        sa.Column('reproduction_result', postgresql.JSONB(), nullable=True),
        sa.Column('code_context', postgresql.JSONB(), nullable=True),
        sa.Column('sandbox_image', sa.String(100), nullable=True),
        sa.Column('validated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('validation_duration', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['issue_id'], ['issues.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_validations_issue', 'validations', ['issue_id'])

    # Create fix_proposals table
    op.create_table(
        'fix_proposals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proposal_id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('issue_id', sa.Integer(), nullable=False),
        sa.Column('validation_id', sa.Integer(), nullable=True),
        sa.Column('suggested_patch', sa.Text(), nullable=False),
        sa.Column('parsed_diff', postgresql.JSONB(), nullable=True),
        sa.Column('affected_files', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('lines_added', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lines_removed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('model_used', sa.String(100), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('generation_attempts', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending_audit'),
        sa.ForeignKeyConstraint(['issue_id'], ['issues.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['validation_id'], ['validations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('proposal_id')
    )
    op.create_index('idx_proposals_issue', 'fix_proposals', ['issue_id'])
    op.create_index('idx_proposals_status', 'fix_proposals', ['status'])

    # Create security_reports table
    op.create_table(
        'security_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('proposal_id', sa.Integer(), nullable=False),
        sa.Column('has_vulnerabilities', sa.Boolean(), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('findings_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('findings_by_severity', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('findings', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('scanners_used', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('dynamic_scan_passed', sa.Boolean(), nullable=True),
        sa.Column('recommendation', sa.String(50), nullable=True),
        sa.Column('scanned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('scan_duration', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['proposal_id'], ['fix_proposals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_id')
    )
    op.create_index('idx_security_proposal', 'security_reports', ['proposal_id'])

    # Create approvals table
    op.create_table(
        'approvals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proposal_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('approved_by', sa.String(100), nullable=True),
        sa.Column('rejected_by', sa.String(100), nullable=True),
        sa.Column('auto_merge', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('comment_id', sa.BigInteger(), nullable=True),
        sa.Column('pr_number', sa.Integer(), nullable=True),
        sa.Column('pr_url', sa.Text(), nullable=True),
        sa.Column('pr_merged', sa.Boolean(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['proposal_id'], ['fix_proposals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_approvals_proposal', 'approvals', ['proposal_id'])
    op.create_index('idx_approvals_status', 'approvals', ['status'])

    # Create audit_log table
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('actor', sa.String(100), nullable=True),
        sa.Column('details', postgresql.JSONB(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_audit_timestamp', 'audit_log', ['timestamp'])
    op.create_index('idx_audit_entity', 'audit_log', ['entity_type', 'entity_id'])
    op.create_index('idx_audit_event_type', 'audit_log', ['event_type'])


def downgrade() -> None:
    # Drop tables in reverse order of creation
    op.drop_index('idx_audit_event_type', 'audit_log')
    op.drop_index('idx_audit_entity', 'audit_log')
    op.drop_index('idx_audit_timestamp', 'audit_log')
    op.drop_table('audit_log')

    op.drop_index('idx_approvals_status', 'approvals')
    op.drop_index('idx_approvals_proposal', 'approvals')
    op.drop_table('approvals')

    op.drop_index('idx_security_proposal', 'security_reports')
    op.drop_table('security_reports')

    op.drop_index('idx_proposals_status', 'fix_proposals')
    op.drop_index('idx_proposals_issue', 'fix_proposals')
    op.drop_table('fix_proposals')

    op.drop_index('idx_validations_issue', 'validations')
    op.drop_table('validations')

    op.drop_index('idx_issues_priority', 'issues')
    op.drop_index('idx_issues_repo', 'issues')
    op.drop_index('idx_issues_status', 'issues')
    op.drop_table('issues')

    op.drop_index('idx_repos_enabled', 'monitored_repos')
    op.drop_table('monitored_repos')
