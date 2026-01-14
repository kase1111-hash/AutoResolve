"""
AutoResolve processing modules.

- monitoring: Webhook handling and issue filtering
- validation: Issue reproduction and context extraction
- fix_generator: LLM-based patch generation
- security_auditor: SAST/DAST security scanning
- approval: PR creation and approval workflow
"""

from modules import approval, fix_generator, monitoring, security_auditor, validation

__all__ = ["monitoring", "validation", "fix_generator", "security_auditor", "approval"]
