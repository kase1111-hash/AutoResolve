"""
Security Audit Module for AutoResolve.

Handles static and dynamic security analysis of proposed fixes.
"""

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
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
SEVERITY_WEIGHTS = {"critical": 10, "high": 7, "medium": 4, "low": 2, "info": 1}

# CWE to severity mapping — covers OWASP Top 10 2021 categories
CWE_SEVERITY_MAP = {
    # A01:2021 Broken Access Control
    "CWE-22": "high",  # Path Traversal
    "CWE-23": "high",  # Relative Path Traversal
    "CWE-35": "high",  # Path Traversal ('.../...//')
    "CWE-59": "medium",  # Improper Link Resolution
    "CWE-200": "low",  # Information Exposure
    "CWE-201": "low",  # Insertion of Sensitive Info Into Sent Data
    "CWE-219": "medium",  # Storage of File with Sensitive Data Under Web Root
    "CWE-264": "high",  # Permissions/Privileges/Access Controls
    "CWE-275": "medium",  # Permission Issues
    "CWE-276": "medium",  # Incorrect Default Permissions
    "CWE-284": "high",  # Improper Access Control
    "CWE-285": "high",  # Improper Authorization
    "CWE-352": "high",  # CSRF
    "CWE-359": "medium",  # Exposure of Private Personal Information
    "CWE-377": "medium",  # Insecure Temporary File
    "CWE-402": "low",  # Transmission of Private Resources into New Sphere
    "CWE-425": "medium",  # Forced Browsing
    "CWE-441": "high",  # Unintended Proxy or Intermediary
    "CWE-497": "low",  # Exposure of System Data to Unauthorized Control Sphere
    "CWE-538": "low",  # Insertion of Sensitive Info into Externally-Accessible File
    "CWE-540": "medium",  # Inclusion of Sensitive Info in Source Code
    "CWE-548": "low",  # Exposure of Info Through Directory Listing
    "CWE-552": "medium",  # Files/Dirs Accessible to External Parties
    "CWE-566": "high",  # Access to User Data Through SQL Injection
    "CWE-601": "medium",  # Open Redirect
    "CWE-639": "high",  # Authorization Bypass Through User-Controlled Key (IDOR)
    "CWE-651": "low",  # Exposure of WSDL File
    "CWE-668": "medium",  # Exposure of Resource to Wrong Sphere
    "CWE-706": "medium",  # Use of Incorrectly-Resolved Name or Reference
    "CWE-862": "high",  # Missing Authorization
    "CWE-863": "high",  # Incorrect Authorization
    "CWE-913": "high",  # Improper Control of Dynamically-Managed Code Resources
    "CWE-922": "medium",  # Insecure Storage of Sensitive Information
    "CWE-1275": "medium",  # Sensitive Cookie with Improper SameSite Attribute
    # A02:2021 Cryptographic Failures
    "CWE-261": "medium",  # Weak Encoding for Password
    "CWE-296": "high",  # Improper Following of a Certificate's Chain of Trust
    "CWE-310": "medium",  # Cryptographic Issues
    "CWE-319": "medium",  # Cleartext Transmission of Sensitive Information
    "CWE-321": "high",  # Use of Hard-coded Cryptographic Key
    "CWE-322": "high",  # Key Exchange without Entity Authentication
    "CWE-323": "high",  # Reusing a Nonce/Key Pair
    "CWE-324": "medium",  # Use of a Key Past its Expiration Date
    "CWE-325": "medium",  # Missing Cryptographic Step
    "CWE-326": "medium",  # Inadequate Encryption Strength
    "CWE-327": "medium",  # Broken/Risky Crypto Algorithm
    "CWE-328": "medium",  # Use of Weak Hash
    "CWE-329": "medium",  # Not Using an Unpredictable IV with CBC Mode
    "CWE-330": "medium",  # Insufficient Randomness
    "CWE-331": "medium",  # Insufficient Entropy
    "CWE-335": "medium",  # Incorrect Usage of Seeds in PRNG
    "CWE-336": "medium",  # Same Seed in PRNG
    "CWE-337": "medium",  # Predictable Seed in PRNG
    "CWE-338": "medium",  # Use of Weak PRNG
    "CWE-340": "medium",  # Generation of Predictable Numbers
    "CWE-347": "high",  # Improper Verification of Cryptographic Signature
    "CWE-523": "medium",  # Unprotected Transport of Credentials
    "CWE-720": "medium",  # OWASP Top Ten 2007 A9 - Insecure Communications
    "CWE-757": "medium",  # Selection of Less-Secure Algorithm During Negotiation
    "CWE-759": "medium",  # Use of a One-Way Hash without a Salt
    "CWE-760": "medium",  # Use of a One-Way Hash with a Predictable Salt
    "CWE-818": "medium",  # Insufficient Transport Layer Protection
    "CWE-916": "medium",  # Use of Password Hash With Insufficient Effort
    # A03:2021 Injection
    "CWE-77": "critical",  # Command Injection
    "CWE-78": "critical",  # OS Command Injection
    "CWE-79": "high",  # XSS
    "CWE-80": "medium",  # Basic XSS
    "CWE-83": "medium",  # XSS in Attribute
    "CWE-87": "medium",  # Improper Neutralization of Alternate XSS Syntax
    "CWE-89": "critical",  # SQL Injection
    "CWE-90": "high",  # LDAP Injection
    "CWE-91": "high",  # XML Injection
    "CWE-93": "medium",  # CRLF Injection
    "CWE-94": "critical",  # Code Injection
    "CWE-95": "critical",  # Eval Injection
    "CWE-96": "critical",  # Static Code Injection
    "CWE-97": "high",  # Server-Side Include Injection
    "CWE-98": "critical",  # PHP Remote File Inclusion (SSTI analog)
    "CWE-99": "high",  # Resource Injection
    "CWE-113": "medium",  # HTTP Response Splitting
    "CWE-116": "medium",  # Improper Encoding or Escaping of Output
    "CWE-138": "medium",  # Improper Neutralization of Special Elements
    "CWE-184": "medium",  # Incomplete List of Disallowed Inputs
    "CWE-470": "high",  # Use of Externally-Controlled Input for Class Selection
    "CWE-471": "medium",  # Modification of Assumed-Immutable Data
    "CWE-502": "critical",  # Deserialization of Untrusted Data
    "CWE-532": "medium",  # Log Injection / Insertion of Sensitive Info into Log File
    "CWE-564": "high",  # SQL Injection: Hibernate
    "CWE-610": "high",  # Externally Controlled Reference to Resource
    "CWE-643": "high",  # XPath Injection
    "CWE-644": "medium",  # Improper Neutralization of HTTP Headers
    "CWE-652": "medium",  # Improper Neutralization of Data within XQuery Expressions
    "CWE-917": "critical",  # Expression Language Injection
    # A04:2021 Insecure Design
    "CWE-209": "low",  # Error Message Info Exposure
    "CWE-256": "high",  # Plaintext Storage of Password
    "CWE-501": "medium",  # Trust Boundary Violation
    "CWE-522": "high",  # Insufficiently Protected Credentials
    "CWE-798": "medium",  # Hardcoded Credentials
    # A05:2021 Security Misconfiguration
    "CWE-2": "low",  # Environment Configuration
    "CWE-11": "low",  # ASP.NET Misconfiguration
    "CWE-13": "low",  # ASP.NET Misconfiguration: Password in Configuration File
    "CWE-15": "low",  # External Control of System/Config Setting
    "CWE-16": "low",  # Configuration
    "CWE-260": "medium",  # Password in Config File
    "CWE-315": "medium",  # Cleartext Storage of Sensitive Info in Cookie
    "CWE-520": "low",  # .NET Misconfiguration
    "CWE-526": "low",  # Exposure of Sensitive Info Through Env Variables
    "CWE-537": "low",  # Java Runtime Error Info Leak
    "CWE-541": "low",  # Info Exposure Through Include Source Code
    "CWE-547": "low",  # Use of Hard-coded, Security-relevant Constants
    "CWE-611": "high",  # XXE
    "CWE-614": "medium",  # Sensitive Cookie in HTTP Session Without 'Secure' Attr
    "CWE-756": "low",  # Missing Custom Error Page
    "CWE-776": "high",  # Improper Restriction of Recursive Entity References in DTDs
    "CWE-942": "medium",  # Permissive CORS Policy
    "CWE-1004": "medium",  # Sensitive Cookie Without 'HttpOnly' Flag
    "CWE-1032": "low",  # OWASP Top Ten 2017 A6 - Security Misconfiguration
    # A06:2021 Vulnerable and Outdated Components (no CWE — dependency scanning)
    # A07:2021 Identification and Authentication Failures
    "CWE-255": "high",  # Credentials Management Errors
    "CWE-259": "high",  # Use of Hard-coded Password
    "CWE-287": "high",  # Improper Authentication
    "CWE-288": "high",  # Authentication Bypass Using an Alternate Path or Channel
    "CWE-290": "high",  # Authentication Bypass by Spoofing
    "CWE-294": "high",  # Authentication Bypass by Capture-replay
    "CWE-295": "high",  # Improper Certificate Validation
    "CWE-297": "high",  # Improper Validation of Certificate with Host Mismatch
    "CWE-300": "high",  # Channel Accessible by Non-Endpoint
    "CWE-302": "high",  # Authentication Bypass by Assumed-Immutable Data
    "CWE-304": "high",  # Missing Critical Step in Authentication
    "CWE-306": "high",  # Missing Authentication for Critical Function
    "CWE-307": "medium",  # Improper Restriction of Excessive Auth Attempts
    "CWE-346": "high",  # Origin Validation Error
    "CWE-384": "high",  # Session Fixation
    "CWE-521": "medium",  # Weak Password Requirements
    "CWE-613": "medium",  # Insufficient Session Expiration
    "CWE-620": "medium",  # Unverified Password Change
    "CWE-640": "medium",  # Weak Password Recovery Mechanism
    "CWE-798": "medium",  # Use of Hard-coded Credentials (also A04)
    # A08:2021 Software and Data Integrity Failures
    "CWE-345": "high",  # Insufficient Verification of Data Authenticity
    "CWE-353": "high",  # Missing Support for Integrity Check
    "CWE-426": "high",  # Untrusted Search Path
    "CWE-494": "critical",  # Download of Code Without Integrity Check
    "CWE-829": "high",  # Inclusion of Functionality from Untrusted Control Sphere
    # A09:2021 Security Logging and Monitoring Failures
    "CWE-117": "medium",  # Improper Output Neutralization for Logs
    "CWE-223": "low",  # Omission of Security-relevant Information
    "CWE-778": "low",  # Insufficient Logging
    # A10:2021 Server-Side Request Forgery
    "CWE-918": "high",  # SSRF
}

# OWASP reference URLs for CWE categories
OWASP_REFERENCES = {
    "CWE-78": "https://owasp.org/Top10/A03_2021-Injection/",
    "CWE-79": "https://owasp.org/Top10/A03_2021-Injection/",
    "CWE-89": "https://owasp.org/Top10/A03_2021-Injection/",
    "CWE-94": "https://owasp.org/Top10/A03_2021-Injection/",
    "CWE-502": "https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures/",
    "CWE-22": "https://owasp.org/Top10/A01_2021-Broken_Access_Control/",
    "CWE-918": "https://owasp.org/Top10/A10_2021-Server-Side_Request_Forgery_%28SSRF%29/",
    "CWE-611": "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
    "CWE-327": "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
    "CWE-798": "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
    "CWE-287": "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
    "CWE-295": "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
    "CWE-352": "https://owasp.org/Top10/A01_2021-Broken_Access_Control/",
    "CWE-284": "https://owasp.org/Top10/A01_2021-Broken_Access_Control/",
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
    python_files = [f for f in affected_files if f.endswith(".py")]
    if not python_files:
        return []

    try:
        cmd = ["bandit", "-r", "-f", "json", "--exit-zero"]
        cmd.extend([str(Path(repo_dir) / f) for f in python_files])

        result = subprocess.run(cmd, capture_output=True, timeout=120)

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
                    recommendation=issue.get("more_info", None),
                )
                findings.append(finding)

            return findings

    except subprocess.TimeoutExpired:
        logger.warning("Bandit scan timed out")
    except FileNotFoundError:
        logger.warning("Bandit not installed, skipping scan")
    except Exception as e:
        logger.error(f"Bandit scan failed: {e}")

    return []


def _bandit_test_to_cwe(test_id: str) -> Optional[str]:
    """Map Bandit test ID to CWE."""
    mapping = {
        "B102": "CWE-78",  # exec used
        "B103": "CWE-94",  # set_bad_file_permissions
        "B104": "CWE-200",  # hardcoded_bind_all_interfaces
        "B105": "CWE-798",  # hardcoded_password_string
        "B106": "CWE-798",  # hardcoded_password_funcarg
        "B107": "CWE-798",  # hardcoded_password_default
        "B108": "CWE-78",  # hardcoded_tmp_directory
        "B110": "CWE-78",  # try_except_pass
        "B201": "CWE-78",  # flask_debug_true
        "B301": "CWE-502",  # pickle
        "B302": "CWE-502",  # marshal
        "B303": "CWE-327",  # md5
        "B304": "CWE-327",  # ciphers
        "B305": "CWE-327",  # cipher_modes
        "B306": "CWE-94",  # mktemp_q
        "B307": "CWE-94",  # eval
        "B308": "CWE-79",  # mark_safe
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
        "B506": "CWE-94",  # yaml_load
        "B507": "CWE-295",  # ssh_no_host_key_verification
        "B601": "CWE-78",  # paramiko_calls
        "B602": "CWE-78",  # subprocess_popen_with_shell_equals_true
        "B603": "CWE-78",  # subprocess_without_shell_equals_true
        "B604": "CWE-78",  # any_other_function_with_shell_equals_true
        "B605": "CWE-78",  # start_process_with_a_shell
        "B606": "CWE-78",  # start_process_with_no_shell
        "B607": "CWE-78",  # start_process_with_partial_path
        "B608": "CWE-89",  # hardcoded_sql_expressions
        "B609": "CWE-78",  # linux_commands_wildcard_injection
        "B610": "CWE-89",  # django_extra_used
        "B611": "CWE-89",  # django_rawsql_used
        "B701": "CWE-94",  # jinja2_autoescape_false
        "B702": "CWE-79",  # use_of_mako_templates
        "B703": "CWE-79",  # django_mark_safe
    }
    return mapping.get(test_id)


def _extract_first_value(data: dict, key: str) -> Optional[str]:
    """Extract the first value from a list or string metadata field."""
    if key not in data:
        return None
    value = data[key]
    if isinstance(value, list) and value:
        return value[0]
    if isinstance(value, str):
        return value
    return None


def _parse_semgrep_match(match: dict) -> Finding:
    """Parse a Semgrep match into a Finding."""
    metadata = match.get("extra", {}).get("metadata", {})
    return Finding(
        finding_id=uuid4(),
        scanner="semgrep",
        rule_id=match.get("check_id", ""),
        cwe=_extract_first_value(metadata, "cwe"),
        owasp=_extract_first_value(metadata, "owasp"),
        severity=metadata.get("severity", "medium").lower(),
        confidence=metadata.get("confidence", "medium").lower(),
        file=match.get("path", ""),
        line_start=match.get("start", {}).get("line", 0),
        line_end=match.get("end", {}).get("line", 0),
        code_snippet=match.get("extra", {}).get("lines", ""),
        message=match.get("extra", {}).get("message", ""),
        recommendation=metadata.get("fix", None),
    )


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
        cmd = ["semgrep", "scan", "--config", "auto", "--json", "--no-git-ignore"]

        # Add configured rulesets
        for ruleset in settings.security.semgrep_rulesets:
            if ruleset != "auto":
                cmd.extend(["--config", ruleset])

        cmd.extend([str(Path(repo_dir) / f) for f in affected_files])

        result = subprocess.run(cmd, capture_output=True, timeout=180, check=False)

        if not result.stdout:
            return []

        data = json.loads(result.stdout)
        return [_parse_semgrep_match(match) for match in data.get("results", [])]

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
        cmd = ["semgrep", "scan", "--config", str(custom_rules_path), "--json"]
        cmd.extend([str(Path(repo_dir) / f) for f in affected_files])

        result = subprocess.run(cmd, capture_output=True, timeout=60)

        findings = []

        if result.stdout:
            data = json.loads(result.stdout)

            for match in data.get("results", []):
                finding = Finding(
                    finding_id=uuid4(),
                    scanner="custom",
                    rule_id=match.get("check_id", ""),
                    severity=match.get("extra", {})
                    .get("metadata", {})
                    .get("severity", "medium")
                    .lower(),
                    file=match.get("path", ""),
                    line_start=match.get("start", {}).get("line", 0),
                    line_end=match.get("end", {}).get("line", 0),
                    code_snippet=match.get("extra", {}).get("lines", ""),
                    message=match.get("extra", {}).get("message", ""),
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
        key = (
            finding.file,
            finding.line_start,
            finding.rule_id[:20] if finding.rule_id else "",
        )
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
    repo_dir: str, affected_files: list[str], language: str
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
    repo_dir: str, proposal: FixProposal, timeout: int = 300
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
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return DynamicScanResult(passed=False, error=f"Failed to apply patch: {e}")

    try:
        # Detect test framework
        repo_path = Path(repo_dir)
        start_time = datetime.now(timezone.utc)

        if (repo_path / "pytest.ini").exists() or (
            repo_path / "pyproject.toml"
        ).exists():
            # Run pytest
            result = subprocess.run(
                ["pytest", "-x", "--timeout", str(timeout // 2)],
                cwd=repo_dir,
                capture_output=True,
                timeout=timeout,
            )
        else:
            # Basic Python syntax check
            result = subprocess.run(
                ["python", "-m", "py_compile"] + proposal.affected_files,
                cwd=repo_dir,
                capture_output=True,
                timeout=60,
            )

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        return DynamicScanResult(
            passed=result.returncode == 0,
            stdout=result.stdout.decode()[-5000:],
            stderr=result.stderr.decode()[-5000:],
            execution_time=duration,
        )

    except subprocess.TimeoutExpired:
        return DynamicScanResult(passed=False, error="Timeout during dynamic analysis")

    except Exception as e:
        return DynamicScanResult(passed=False, error=str(e))

    finally:
        # Revert patch
        subprocess.run(["git", "checkout", "."], cwd=repo_dir, capture_output=True)


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
    proposal: FixProposal, repo_dir: str, language: str
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
    start_time = datetime.now(timezone.utc)
    scanners_used = []

    # Apply patch temporarily
    try:
        subprocess.run(
            ["git", "apply"],
            input=proposal.suggested_patch.encode(),
            cwd=repo_dir,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to apply patch for audit: {e}")
        return SecurityReport(
            proposal_id=proposal.proposal_id,
            has_vulnerabilities=True,
            risk_score=1.0,
            findings=[],
            recommendation="reject",
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
        critical_findings = [
            f for f in findings if assess_severity(f) in ("critical", "high")
        ]

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

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
            scan_duration=duration,
        )

        report.recommendation = generate_recommendation(report)

        return report

    finally:
        # Revert patch
        subprocess.run(["git", "checkout", "."], cwd=repo_dir, capture_output=True)
