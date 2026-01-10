"""
Security Audit Module for AutoResolve.

Handles static and dynamic security analysis of proposed fixes.
"""

import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.config import get_settings
from models.schemas import (
    DynamicScanResult,
    Finding,
    FixProposal,
    SecurityReport,
)

logger = logging.getLogger(__name__)

# Severity weights for risk scoring
SEVERITY_WEIGHTS = {
    "critical": 10,
    "high": 7,
    "medium": 4,
    "low": 2,
    "info": 1
}

# CWE to severity mapping
CWE_SEVERITY_MAP = {
    # Critical
    "CWE-78": "critical",   # OS Command Injection
    "CWE-89": "critical",   # SQL Injection
    "CWE-94": "critical",   # Code Injection
    "CWE-502": "critical",  # Deserialization

    # High
    "CWE-79": "high",       # XSS
    "CWE-22": "high",       # Path Traversal
    "CWE-918": "high",      # SSRF
    "CWE-611": "high",      # XXE
    "CWE-295": "high",      # Improper Cert Validation

    # Medium
    "CWE-327": "medium",    # Broken Crypto
    "CWE-330": "medium",    # Insufficient Randomness
    "CWE-532": "medium",    # Log Injection
    "CWE-798": "medium",    # Hardcoded Credentials

    # Low
    "CWE-200": "low",       # Information Exposure
    "CWE-209": "low",       # Error Message Exposure
}


def run_bandit(repo_dir: str, affected_files: list[str]) -> list[Finding]:
    """
    Run Bandit static analysis on Python files.

    Args:
        repo_dir: Path to repository
        affected_files: List of files to scan

    Returns:
        List of security findings
    """
    python_files = [f for f in affected_files if f.endswith('.py')]
    if not python_files:
        return []

    try:
        cmd = ["bandit", "-r", "-f", "json", "--exit-zero"]
        cmd.extend([str(Path(repo_dir) / f) for f in python_files])

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120
        )

        if result.stdout:
            data = json.loads(result.stdout)
            findings = []

            for issue in data.get("results", []):
                finding = Finding(
                    finding_id=uuid4(),
                    scanner="bandit",
                    rule_id=issue.get("test_id", ""),
                    cwe=_bandit_test_to_cwe(issue.get("test_id", "")),
                    severity=issue.get("issue_severity", "medium").lower(),
                    confidence=issue.get("issue_confidence", "medium").lower(),
                    file=issue.get("filename", ""),
                    line_start=issue.get("line_number", 0),
                    line_end=issue.get("line_number", 0),
                    code_snippet=issue.get("code", ""),
                    message=issue.get("issue_text", ""),
                    recommendation=issue.get("more_info", None)
                )
                findings.append(finding)

            return findings

    except subprocess.TimeoutExpired:
        logger.warning("Bandit scan timed out")
    except Exception as e:
        logger.error(f"Bandit scan failed: {e}")

    return []


def _bandit_test_to_cwe(test_id: str) -> Optional[str]:
    """Map Bandit test ID to CWE."""
    mapping = {
        "B102": "CWE-78",   # exec used
        "B103": "CWE-94",   # set_bad_file_permissions
        "B104": "CWE-200",  # hardcoded_bind_all_interfaces
        "B105": "CWE-798",  # hardcoded_password_string
        "B106": "CWE-798",  # hardcoded_password_funcarg
        "B107": "CWE-798",  # hardcoded_password_default
        "B108": "CWE-78",   # hardcoded_tmp_directory
        "B110": "CWE-78",   # try_except_pass
        "B201": "CWE-78",   # flask_debug_true
        "B301": "CWE-502",  # pickle
        "B302": "CWE-502",  # marshal
        "B303": "CWE-327",  # md5
        "B304": "CWE-327",  # ciphers
        "B305": "CWE-327",  # cipher_modes
        "B306": "CWE-94",   # mktemp_q
        "B307": "CWE-94",   # eval
        "B308": "CWE-79",   # mark_safe
        "B310": "CWE-918",  # urllib_urlopen
        "B311": "CWE-330",  # random
        "B312": "CWE-295",  # telnetlib
        "B313": "CWE-611",  # xml_bad_cElementTree
        "B314": "CWE-611",  # xml_bad_ElementTree
        "B315": "CWE-611",  # xml_bad_expatreader
        "B316": "CWE-611",  # xml_bad_expatbuilder
        "B317": "CWE-611",  # xml_bad_sax
        "B318": "CWE-611",  # xml_bad_minidom
        "B319": "CWE-611",  # xml_bad_pulldom
        "B320": "CWE-611",  # xml_bad_etree
        "B321": "CWE-295",  # ftplib
        "B323": "CWE-295",  # unverified_context
        "B324": "CWE-327",  # hashlib_new_insecure_functions
        "B501": "CWE-295",  # request_with_no_cert_validation
        "B502": "CWE-327",  # ssl_with_bad_version
        "B503": "CWE-327",  # ssl_with_bad_defaults
        "B504": "CWE-327",  # ssl_with_no_version
        "B505": "CWE-327",  # weak_cryptographic_key
        "B506": "CWE-94",   # yaml_load
        "B507": "CWE-295",  # ssh_no_host_key_verification
        "B601": "CWE-78",   # paramiko_calls
        "B602": "CWE-78",   # subprocess_popen_with_shell_equals_true
        "B603": "CWE-78",   # subprocess_without_shell_equals_true
        "B604": "CWE-78",   # any_other_function_with_shell_equals_true
        "B605": "CWE-78",   # start_process_with_a_shell
        "B606": "CWE-78",   # start_process_with_no_shell
        "B607": "CWE-78",   # start_process_with_partial_path
        "B608": "CWE-89",   # hardcoded_sql_expressions
        "B609": "CWE-78",   # linux_commands_wildcard_injection
        "B610": "CWE-89",   # django_extra_used
        "B611": "CWE-89",   # django_rawsql_used
        "B701": "CWE-94",   # jinja2_autoescape_false
        "B702": "CWE-79",   # use_of_mako_templates
        "B703": "CWE-79",   # django_mark_safe
    }
    return mapping.get(test_id)


def run_semgrep(repo_dir: str, affected_files: list[str]) -> list[Finding]:
    """
    Run Semgrep static analysis.

    Args:
        repo_dir: Path to repository
        affected_files: List of files to scan

    Returns:
        List of security findings
    """
    settings = get_settings()

    try:
        cmd = [
            "semgrep", "scan",
            "--config", "auto",
            "--json",
            "--no-git-ignore"
        ]

        # Add configured rulesets
        for ruleset in settings.security.semgrep_rulesets:
            if ruleset != "auto":
                cmd.extend(["--config", ruleset])

        cmd.extend([str(Path(repo_dir) / f) for f in affected_files])

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=180
        )

        findings = []

        if result.stdout:
            data = json.loads(result.stdout)

            for match in data.get("results", []):
                # Extract CWE from metadata
                cwe = None
                owasp = None
                metadata = match.get("extra", {}).get("metadata", {})

                if "cwe" in metadata:
                    cwe_list = metadata["cwe"]
                    if isinstance(cwe_list, list) and cwe_list:
                        cwe = cwe_list[0]
                    elif isinstance(cwe_list, str):
                        cwe = cwe_list

                if "owasp" in metadata:
                    owasp_list = metadata["owasp"]
                    if isinstance(owasp_list, list) and owasp_list:
                        owasp = owasp_list[0]
                    elif isinstance(owasp_list, str):
                        owasp = owasp_list

                finding = Finding(
                    finding_id=uuid4(),
                    scanner="semgrep",
                    rule_id=match.get("check_id", ""),
                    cwe=cwe,
                    owasp=owasp,
                    severity=metadata.get("severity", "medium").lower(),
                    confidence=metadata.get("confidence", "medium").lower(),
                    file=match.get("path", ""),
                    line_start=match.get("start", {}).get("line", 0),
                    line_end=match.get("end", {}).get("line", 0),
                    code_snippet=match.get("extra", {}).get("lines", ""),
                    message=match.get("extra", {}).get("message", ""),
                    recommendation=metadata.get("fix", None)
                )
                findings.append(finding)

        return findings

    except subprocess.TimeoutExpired:
        logger.warning("Semgrep scan timed out")
    except FileNotFoundError:
        logger.warning("Semgrep not installed, skipping scan")
    except Exception as e:
        logger.error(f"Semgrep scan failed: {e}")

    return []


def run_custom_rules(repo_dir: str, affected_files: list[str]) -> list[Finding]:
    """
    Run custom security rules if present in repository.

    Args:
        repo_dir: Path to repository
        affected_files: List of files to scan

    Returns:
        List of security findings
    """
    custom_rules_path = Path(repo_dir) / ".semgrep.yml"

    if not custom_rules_path.exists():
        return []

    try:
        cmd = [
            "semgrep", "scan",
            "--config", str(custom_rules_path),
            "--json"
        ]
        cmd.extend([str(Path(repo_dir) / f) for f in affected_files])

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=60
        )

        findings = []

        if result.stdout:
            data = json.loads(result.stdout)

            for match in data.get("results", []):
                finding = Finding(
                    finding_id=uuid4(),
                    scanner="custom",
                    rule_id=match.get("check_id", ""),
                    severity=match.get("extra", {}).get("metadata", {}).get("severity", "medium").lower(),
                    file=match.get("path", ""),
                    line_start=match.get("start", {}).get("line", 0),
                    line_end=match.get("end", {}).get("line", 0),
                    code_snippet=match.get("extra", {}).get("lines", ""),
                    message=match.get("extra", {}).get("message", "")
                )
                findings.append(finding)

        return findings

    except Exception as e:
        logger.error(f"Custom rules scan failed: {e}")
        return []


def assess_severity(finding: Finding) -> str:
    """
    Assess the severity of a finding.

    Args:
        finding: Security finding

    Returns:
        Severity level
    """
    # Check CWE mapping first
    if finding.cwe and finding.cwe in CWE_SEVERITY_MAP:
        return CWE_SEVERITY_MAP[finding.cwe]

    # Fall back to scanner-provided severity
    if finding.severity:
        return finding.severity.lower()

    return "medium"


def compute_risk_score(findings: list[Finding]) -> float:
    """
    Compute overall risk score.

    Args:
        findings: List of security findings

    Returns:
        Risk score (0.0 = safe, 1.0 = critical risk)
    """
    if not findings:
        return 0.0

    total_weight = sum(SEVERITY_WEIGHTS.get(assess_severity(f), 4) for f in findings)
    max_possible = len(findings) * SEVERITY_WEIGHTS["critical"]

    return min(1.0, total_weight / max_possible)


def deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """
    Remove duplicate findings from different scanners.

    Args:
        findings: List of all findings

    Returns:
        Deduplicated list
    """
    seen = set()
    unique = []

    for finding in findings:
        # Create a unique key based on file, line, and rule type
        key = (finding.file, finding.line_start, finding.rule_id[:20] if finding.rule_id else "")
        if key not in seen:
            seen.add(key)
            unique.append(finding)

    return unique


def filter_false_positives(findings: list[Finding]) -> list[Finding]:
    """
    Filter out likely false positives.

    Args:
        findings: List of findings

    Returns:
        Filtered list
    """
    settings = get_settings()
    filtered = []

    for finding in findings:
        is_fp = False

        # Check against false positive patterns
        for pattern in settings.security.false_positive_patterns:
            if re.match(pattern, finding.file):
                is_fp = True
                break

        if not is_fp:
            filtered.append(finding)
        else:
            finding.false_positive = True

    return filtered


def run_static_analysis(
    repo_dir: str,
    affected_files: list[str],
    language: str
) -> list[Finding]:
    """
    Run all static analysis tools.

    Args:
        repo_dir: Path to repository
        affected_files: List of files to scan
        language: Primary language

    Returns:
        Combined list of findings
    """
    settings = get_settings()
    findings = []

    # Run Bandit for Python
    if language == "python" and "bandit" in settings.security.enabled_scanners:
        bandit_findings = run_bandit(repo_dir, affected_files)
        findings.extend(bandit_findings)
        logger.info(f"Bandit found {len(bandit_findings)} issues")

    # Run Semgrep for all languages
    if "semgrep" in settings.security.enabled_scanners:
        semgrep_findings = run_semgrep(repo_dir, affected_files)
        findings.extend(semgrep_findings)
        logger.info(f"Semgrep found {len(semgrep_findings)} issues")

    # Run custom rules
    custom_findings = run_custom_rules(repo_dir, affected_files)
    findings.extend(custom_findings)
    logger.info(f"Custom rules found {len(custom_findings)} issues")

    # Deduplicate and filter
    findings = deduplicate_findings(findings)
    findings = filter_false_positives(findings)

    return findings


def run_dynamic_analysis(
    repo_dir: str,
    proposal: FixProposal,
    timeout: int = 300
) -> DynamicScanResult:
    """
    Run dynamic analysis (fuzz testing) on patched code.

    Args:
        repo_dir: Path to repository
        proposal: Fix proposal with patch
        timeout: Execution timeout

    Returns:
        Dynamic scan result
    """
    # Apply the patch
    try:
        subprocess.run(
            ["git", "apply"],
            input=proposal.suggested_patch.encode(),
            cwd=repo_dir,
            check=True
        )
    except subprocess.CalledProcessError as e:
        return DynamicScanResult(
            passed=False,
            error=f"Failed to apply patch: {e}"
        )

    try:
        # Detect test framework
        repo_path = Path(repo_dir)
        start_time = datetime.utcnow()

        if (repo_path / "pytest.ini").exists() or (repo_path / "pyproject.toml").exists():
            # Run pytest
            result = subprocess.run(
                ["pytest", "-x", "--timeout", str(timeout // 2)],
                cwd=repo_dir,
                capture_output=True,
                timeout=timeout
            )
        else:
            # Basic Python syntax check
            result = subprocess.run(
                ["python", "-m", "py_compile"] + proposal.affected_files,
                cwd=repo_dir,
                capture_output=True,
                timeout=60
            )

        duration = (datetime.utcnow() - start_time).total_seconds()

        return DynamicScanResult(
            passed=result.returncode == 0,
            stdout=result.stdout.decode()[-5000:],
            stderr=result.stderr.decode()[-5000:],
            execution_time=duration
        )

    except subprocess.TimeoutExpired:
        return DynamicScanResult(
            passed=False,
            error="Timeout during dynamic analysis"
        )

    except Exception as e:
        return DynamicScanResult(
            passed=False,
            error=str(e)
        )

    finally:
        # Revert patch
        subprocess.run(
            ["git", "checkout", "."],
            cwd=repo_dir,
            capture_output=True
        )


def generate_recommendation(report: SecurityReport) -> str:
    """
    Generate a recommendation based on security findings.

    Args:
        report: Security report

    Returns:
        Recommendation: "approve", "review", or "reject"
    """
    # Immediate rejection criteria
    if report.findings_by_severity.get("critical", 0) > 0:
        return "reject"

    if report.findings_by_severity.get("high", 0) > 2:
        return "reject"

    # Needs human review
    if report.findings_by_severity.get("high", 0) > 0:
        return "review"

    if report.findings_by_severity.get("medium", 0) > 3:
        return "review"

    if report.dynamic_scan_passed is False:
        return "review"

    if report.risk_score > 0.3:
        return "review"

    # Safe to proceed
    return "approve"


async def audit_fix(
    proposal: FixProposal,
    repo_dir: str,
    language: str
) -> SecurityReport:
    """
    Complete security audit of a fix proposal.

    Args:
        proposal: Fix proposal to audit
        repo_dir: Path to repository
        language: Programming language

    Returns:
        Complete security report
    """
    settings = get_settings()
    start_time = datetime.utcnow()
    scanners_used = []

    # Apply patch temporarily
    try:
        subprocess.run(
            ["git", "apply"],
            input=proposal.suggested_patch.encode(),
            cwd=repo_dir,
            check=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to apply patch for audit: {e}")
        return SecurityReport(
            proposal_id=proposal.proposal_id,
            has_vulnerabilities=True,
            risk_score=1.0,
            findings=[],
            recommendation="reject"
        )

    try:
        # Run static analysis
        findings = run_static_analysis(repo_dir, proposal.affected_files, language)
        scanners_used = list(set(f.scanner for f in findings))

        # Run dynamic analysis if enabled
        dynamic_result = None
        if settings.security.enable_dynamic_scan:
            # Revert first since static analysis was on patched code
            subprocess.run(["git", "checkout", "."], cwd=repo_dir, capture_output=True)

            dynamic_result = run_dynamic_analysis(
                repo_dir, proposal, settings.security.dynamic_scan_timeout
            )

        # Count findings by severity
        findings_by_severity = {}
        for finding in findings:
            severity = assess_severity(finding)
            findings_by_severity[severity] = findings_by_severity.get(severity, 0) + 1

        # Identify critical findings
        critical_findings = [f for f in findings if assess_severity(f) in ("critical", "high")]

        duration = (datetime.utcnow() - start_time).total_seconds()

        report = SecurityReport(
            proposal_id=proposal.proposal_id,
            has_vulnerabilities=len(findings) > 0,
            risk_score=compute_risk_score(findings),
            findings_count=len(findings),
            findings_by_severity=findings_by_severity,
            findings=findings,
            critical_findings=critical_findings,
            scanners_used=scanners_used,
            dynamic_scan_passed=dynamic_result.passed if dynamic_result else None,
            scan_duration=duration
        )

        report.recommendation = generate_recommendation(report)

        return report

    finally:
        # Revert patch
        subprocess.run(
            ["git", "checkout", "."],
            cwd=repo_dir,
            capture_output=True
        )
