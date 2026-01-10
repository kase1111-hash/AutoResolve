"""
AutoResolve processing modules.

- monitoring: Webhook handling and issue filtering
- validation: Issue reproduction and context extraction
- fix_generator: LLM-based patch generation
- security_auditor: SAST/DAST security scanning
- approval: PR creation and approval workflow
"""

from modules import monitoring, validation, fix_generator, security_auditor, approval

__all__ = ["monitoring", "validation", "fix_generator", "security_auditor", "approval"]
