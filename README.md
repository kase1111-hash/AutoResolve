# AutoResolve — Automated GitHub Issue Resolution System
## Technical Specification v1.0

**Tagline:** From issue to merge, securely automated.

---

## 1. System Overview

### 1.1 Purpose

AutoResolve monitors GitHub repositories for bug reports, validates their reproducibility in isolated sandboxes, generates AI-assisted patches, audits those patches for security vulnerabilities, and applies changes only after explicit owner approval. The system provides a fully auditable trail from issue detection to secure patch deployment.

### 1.2 Core Value Proposition

| Metric | Target | Current Manual Baseline |
|--------|--------|------------------------|
| Issue triage latency | < 60 seconds | 4-24 hours |
| Security false-negative rate | < 5% | ~15% (human review) |
| Fix acceptance rate | > 70% | N/A |
| Time to first patch proposal | < 10 minutes | 1-7 days |

### 1.3 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AUTORESOLVE CORE                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         INGRESS LAYER                                   │   │
│  │  ┌───────────────┐              ┌───────────────┐                      │   │
│  │  │    GitHub     │              │   Fallback    │                      │   │
│  │  │   Webhooks    │              │    Poller     │                      │   │
│  │  │  POST /webhook│              │  (5 min cron) │                      │   │
│  │  └───────┬───────┘              └───────┬───────┘                      │   │
│  │          └──────────────┬───────────────┘                              │   │
│  │                         ▼                                               │   │
│  │              ┌───────────────────┐                                      │   │
│  │              │  MONITORING       │                                      │   │
│  │              │  MODULE           │                                      │   │
│  │              │  • Filter by label│                                      │   │
│  │              │  • Keyword detect │                                      │   │
│  │              │  • Deduplication  │                                      │   │
│  │              └─────────┬─────────┘                                      │   │
│  └────────────────────────┼────────────────────────────────────────────────┘   │
│                           ▼                                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐    │
│  │                         TASK QUEUE (Celery + RabbitMQ)                 │    │
│  └────────────────────────┬───────────────────────────────────────────────┘    │
│                           │                                                     │
│         ┌─────────────────┼─────────────────┬─────────────────┐                │
│         ▼                 ▼                 ▼                 ▼                │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐        │
│  │ VALIDATION  │   │    FIX      │   │  SECURITY   │   │  APPROVAL   │        │
│  │   MODULE    │──▶│ GENERATION  │──▶│   AUDIT     │──▶│   MODULE    │        │
│  │             │   │   MODULE    │   │   MODULE    │   │             │        │
│  │ • Parse     │   │             │   │             │   │ • Comment   │        │
│  │ • Clone     │   │ • LLM Patch │   │ • Bandit    │   │ • Poll      │        │
│  │ • Reproduce │   │ • Syntax OK │   │ • Semgrep   │   │ • Create PR │        │
│  │ • Sandbox   │   │ • Diff Gen  │   │ • Fuzz Test │   │ • Merge     │        │
│  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘        │
│         │                 │                 │                 │                │
│         └─────────────────┴─────────────────┴─────────────────┘                │
│                                     │                                           │
│                                     ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         STORAGE LAYER                                   │   │
│  │  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐             │   │
│  │  │  PostgreSQL   │   │  Redis Cache  │   │  Artifact     │             │   │
│  │  │  (Issues,     │   │  (Rate limits,│   │  Storage      │             │   │
│  │  │   Proposals,  │   │   Sessions)   │   │  (Diffs, Logs)│             │   │
│  │  │   Audit Logs) │   │               │   │               │             │   │
│  │  └───────────────┘   └───────────────┘   └───────────────┘             │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                         EXTERNAL SERVICES                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                          │
│  │  GitHub API  │  │  OpenAI API  │  │   Docker     │                          │
│  │  (Issues,PRs)│  │  (GPT-4)     │  │  (Sandbox)   │                          │
│  └──────────────┘  └──────────────┘  └──────────────┘                          │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1.4 Module Summary

| Module | Trigger | Input | Output | Next Stage |
|--------|---------|-------|--------|------------|
| Monitoring | Webhook / Poll | GitHub event | Filtered issue | Validation |
| Validation | Queue pickup | Issue metadata | Reproduction result | Fix Generation |
| Fix Generation | Valid issue | Code context + error | Unified diff | Security Audit |
| Security Audit | Proposed patch | Diff + patched files | Vulnerability report | Approval |
| Approval | Clean audit | Patch + report | PR URL or rejection | Complete |

---

## 2. Module Specifications

### 2.1 Monitoring Module

**File:** `modules/monitoring.py`

#### 2.1.1 Responsibilities

| Function | Description |
|----------|-------------|
| `register_webhook()` | Configure GitHub App webhook subscription |
| `handle_webhook()` | Process incoming webhook POST payloads |
| `filter_issue()` | Determine if issue qualifies for processing |
| `poll_repositories()` | Fallback polling for missed webhooks |
| `deduplicate()` | Prevent reprocessing of known issues |
| `enqueue_issue()` | Push qualified issue to task queue |

#### 2.1.2 Webhook Handler Logic

```python
FUNCTION handle_webhook(payload: GitHubWebhookPayload) -> Optional[QueuedIssue]:
    # Validate webhook signature
    IF NOT verify_signature(payload.headers["X-Hub-Signature-256"], payload.body):
        RAISE SecurityError("Invalid webhook signature")
    
    event_type = payload.headers["X-GitHub-Event"]
    
    IF event_type != "issues":
        RETURN None
    
    action = payload.body["action"]
    IF action NOT IN ["opened", "reopened", "labeled"]:
        RETURN None
    
    issue = payload.body["issue"]
    repo = payload.body["repository"]
    
    # Filter by labels and keywords
    IF NOT should_process(issue):
        RETURN None
    
    # Check deduplication
    IF is_already_queued(repo.full_name, issue.number):
        RETURN None
    
    queued = QueuedIssue(
        issue_id=issue.number,
        repo_url=repo.html_url,
        repo_full_name=repo.full_name,
        title=issue.title,
        body=issue.body,
        labels=[l.name for l in issue.labels],
        author=issue.user.login,
        created_at=issue.created_at
    )
    
    enqueue(queued)
    RETURN queued
```

#### 2.1.3 Issue Filtering Rules

```python
FilterConfig = {
    "trigger_labels": ["bug", "error", "defect", "crash", "regression"],
    "trigger_keywords": [
        "TypeError", "ValueError", "AttributeError", "KeyError",
        "traceback", "stack trace", "exception", "fails", "broken",
        "doesn't work", "error when", "crash when"
    ],
    "exclude_labels": ["wontfix", "duplicate", "invalid", "question"],
    "exclude_authors": ["dependabot", "renovate", "github-actions"],
    "min_body_length": 50,
    "max_age_days": 30
}

FUNCTION should_process(issue: GitHubIssue) -> bool:
    # Exclude by label
    IF any(label IN FilterConfig.exclude_labels FOR label IN issue.labels):
        RETURN False
    
    # Exclude bot authors
    IF issue.author IN FilterConfig.exclude_authors:
        RETURN False
    
    # Check minimum content
    IF len(issue.body) < FilterConfig.min_body_length:
        RETURN False
    
    # Check age
    IF issue.age_days > FilterConfig.max_age_days:
        RETURN False
    
    # Trigger by label
    IF any(label IN FilterConfig.trigger_labels FOR label IN issue.labels):
        RETURN True
    
    # Trigger by keyword (case-insensitive)
    combined_text = (issue.title + " " + issue.body).lower()
    IF any(keyword.lower() IN combined_text FOR keyword IN FilterConfig.trigger_keywords):
        RETURN True
    
    RETURN False
```

#### 2.1.4 Fallback Poller

```python
FUNCTION poll_repositories(repos: List[str], since_minutes: int = 10) -> List[QueuedIssue]:
    """
    Poll repos for issues created/updated since last check.
    Runs every 5 minutes via Celery beat.
    """
    queued = []
    since = datetime.utcnow() - timedelta(minutes=since_minutes)
    
    FOR repo_full_name IN repos:
        issues = github_api.get_issues(
            repo=repo_full_name,
            state="open",
            since=since.isoformat(),
            sort="updated",
            direction="desc"
        )
        
        FOR issue IN issues:
            IF should_process(issue) AND NOT is_already_queued(repo_full_name, issue.number):
                queued.append(create_queued_issue(repo_full_name, issue))
    
    RETURN queued
```

#### 2.1.5 Output Schema

```python
QueuedIssue = {
    "queue_id": str,                # Internal UUID
    "issue_id": int,                # GitHub issue number
    "repo_url": str,                # https://github.com/org/repo
    "repo_full_name": str,          # org/repo
    "title": str,
    "body": str,
    "labels": List[str],
    "author": str,
    "created_at": datetime,
    "queued_at": datetime,
    "priority": int,                # 1 (high) - 5 (low)
    "status": str                   # "pending" | "processing" | "completed" | "failed"
}
```

#### 2.1.6 Configuration

```python
MonitoringConfig = {
    "webhook_secret": str,          # GitHub webhook secret
    "webhook_path": "/webhook/github",
    "poll_interval_minutes": 5,
    "poll_lookback_minutes": 10,
    "max_queue_size": 1000,
    "priority_labels": {            # Label → priority mapping
        "critical": 1,
        "high-priority": 2,
        "bug": 3
    },
    "rate_limit_buffer": 100        # Stop polling if API calls remaining < buffer
}
```

---

### 2.2 Validation Module

**File:** `modules/validation.py`

#### 2.2.1 Responsibilities

| Function | Description |
|----------|-------------|
| `parse_issue()` | Extract structured info from issue text |
| `clone_repository()` | Shallow clone repo to temp directory |
| `setup_sandbox()` | Create isolated Docker container |
| `reproduce_issue()` | Run tests/code to confirm bug exists |
| `extract_context()` | Identify affected files, functions, line numbers |
| `compute_validity_score()` | Rate reproduction confidence |

#### 2.2.2 Issue Parsing Pipeline

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Raw Issue     │───▶│   LLM Parser    │───▶│   Structured    │
│   Title + Body  │    │   (GPT-4o)      │    │   IssueContext  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Regex Fallback │
                    │  • File paths   │
                    │  • Function names│
                    │  • Error types  │
                    └─────────────────┘
```

#### 2.2.3 LLM Parsing Prompt

```
You are a bug report parser. Extract structured information from this GitHub issue.

Issue Title: {title}
Issue Body:
{body}

Extract the following (respond in JSON only):
{
  "error_type": "The exception or error class (e.g., TypeError, NullPointerException)",
  "error_message": "The specific error message if present",
  "affected_files": ["List of file paths mentioned"],
  "affected_functions": ["List of function/method names mentioned"],
  "stack_trace": "Full stack trace if present, else null",
  "reproduction_steps": ["Ordered list of steps to reproduce"],
  "expected_behavior": "What should happen",
  "actual_behavior": "What actually happens",
  "environment": {
    "os": "Operating system if mentioned",
    "python_version": "Python version if mentioned",
    "dependencies": ["Relevant package versions"]
  },
  "code_snippets": ["Any code blocks from the issue"],
  "confidence": 0.0-1.0
}

If information is not present, use null. Be conservative with confidence.
```

#### 2.2.4 Sandbox Execution

```python
FUNCTION reproduce_issue(issue: QueuedIssue, context: IssueContext) -> ReproductionResult:
    # Clone repository
    repo_dir = clone_repository(
        url=issue.repo_url,
        depth=1,
        branch=get_default_branch(issue.repo_full_name)
    )
    
    # Detect language and runtime
    language = detect_language(repo_dir)
    sandbox_image = get_sandbox_image(language)
    
    # Build reproduction command
    IF context.reproduction_steps:
        commands = generate_commands_from_steps(context.reproduction_steps)
    ELSE:
        commands = get_default_test_commands(language)
    
    # Execute in sandbox
    container = docker.create_container(
        image=sandbox_image,
        volumes={repo_dir: "/code"},
        network_mode="none",           # No network access
        mem_limit="512m",
        cpu_quota=50000,               # 50% of one CPU
        timeout=300                    # 5 minute max
    )
    
    TRY:
        result = container.run(commands)
        
        # Check if error matches expected
        IF context.error_type AND context.error_type IN result.stderr:
            validity = "confirmed"
            match_score = compute_similarity(context.error_message, result.stderr)
        ELIF result.exit_code != 0:
            validity = "partial"       # Some error, but not exact match
            match_score = 0.5
        ELSE:
            validity = "not_reproduced"
            match_score = 0.0
        
        RETURN ReproductionResult(
            valid=(validity == "confirmed"),
            validity_status=validity,
            match_score=match_score,
            stdout=result.stdout[-5000:],  # Last 5KB
            stderr=result.stderr[-5000:],
            exit_code=result.exit_code,
            error_signature=extract_error_signature(result.stderr),
            execution_time=result.duration
        )
    
    FINALLY:
        container.cleanup()
        cleanup_repo(repo_dir)
```

#### 2.2.5 Context Extraction

```python
FUNCTION extract_context(repo_dir: str, context: IssueContext, result: ReproductionResult) -> CodeContext:
    """
    Extract the specific code context needed for fix generation.
    """
    affected_files = []
    
    # From parsed issue
    FOR file_path IN context.affected_files:
        IF exists(repo_dir / file_path):
            affected_files.append(file_path)
    
    # From stack trace
    IF result.error_signature:
        trace_files = parse_stack_trace_files(result.stderr)
        affected_files.extend(trace_files)
    
    # Deduplicate and validate
    affected_files = list(set(affected_files))
    affected_files = [f for f in affected_files if is_code_file(f)]
    
    # Extract function bodies
    functions = []
    FOR file_path IN affected_files:
        full_path = repo_dir / file_path
        ast_tree = parse_file(full_path)
        
        FOR func_name IN context.affected_functions:
            func_node = find_function(ast_tree, func_name)
            IF func_node:
                functions.append(FunctionContext(
                    file=file_path,
                    name=func_name,
                    start_line=func_node.lineno,
                    end_line=func_node.end_lineno,
                    source=get_source_lines(full_path, func_node.lineno, func_node.end_lineno),
                    imports=extract_imports(ast_tree)
                ))
    
    # If no specific functions, extract error location
    IF NOT functions AND result.error_signature:
        line_number = extract_line_from_trace(result.stderr)
        IF line_number:
            functions.append(extract_context_around_line(
                file=affected_files[0],
                line=line_number,
                context_lines=20
            ))
    
    RETURN CodeContext(
        affected_files=affected_files,
        functions=functions,
        error_signature=result.error_signature,
        test_command=get_test_command(repo_dir),
        language=detect_language(repo_dir)
    )
```

#### 2.2.6 Output Schema

```python
IssueContext = {
    "error_type": Optional[str],
    "error_message": Optional[str],
    "affected_files": List[str],
    "affected_functions": List[str],
    "stack_trace": Optional[str],
    "reproduction_steps": List[str],
    "expected_behavior": Optional[str],
    "actual_behavior": Optional[str],
    "environment": EnvironmentInfo,
    "code_snippets": List[str],
    "parse_confidence": float
}

ReproductionResult = {
    "valid": bool,
    "validity_status": str,         # "confirmed" | "partial" | "not_reproduced" | "error"
    "match_score": float,           # 0.0 - 1.0
    "stdout": str,
    "stderr": str,
    "exit_code": int,
    "error_signature": Optional[str],
    "execution_time": float,
    "sandbox_image": str,
    "reproduced_at": datetime
}

CodeContext = {
    "affected_files": List[str],
    "functions": List[FunctionContext],
    "error_signature": str,
    "test_command": str,
    "language": str,
    "repo_commit": str              # SHA of tested commit
}

FunctionContext = {
    "file": str,
    "name": str,
    "start_line": int,
    "end_line": int,
    "source": str,
    "imports": List[str]
}

ValidationResult = {
    "issue_id": int,
    "repo_full_name": str,
    "valid": bool,
    "validity_status": str,
    "issue_context": IssueContext,
    "reproduction_result": ReproductionResult,
    "code_context": Optional[CodeContext],
    "validated_at": datetime,
    "validation_duration": float
}
```

#### 2.2.7 Sandbox Images

```python
SANDBOX_IMAGES = {
    "python": {
        "default": "python:3.11-slim",
        "3.8": "python:3.8-slim",
        "3.9": "python:3.9-slim",
        "3.10": "python:3.10-slim",
        "3.11": "python:3.11-slim",
        "3.12": "python:3.12-slim"
    }
}

# Default test commands (Python-only)
DEFAULT_TEST_COMMANDS = {
    "python": [
        "pip install -r requirements.txt 2>/dev/null || true",
        "pip install pytest 2>/dev/null || true",
        "pytest -v --tb=short 2>&1 || python -m unittest discover 2>&1"
    ]
}
```

#### 2.2.8 Configuration

```python
ValidationConfig = {
    "clone_depth": 1,
    "clone_timeout_seconds": 120,
    "sandbox_timeout_seconds": 300,
    "sandbox_memory_limit": "512m",
    "sandbox_cpu_quota": 50000,
    "sandbox_network": "none",
    "max_stderr_size": 10000,
    "max_stdout_size": 10000,
    "context_lines_around_error": 20,
    "min_match_score_for_valid": 0.6,
    "llm_parse_model": "gpt-4o",
    "llm_parse_temperature": 0.1,
    "temp_directory": "/tmp/autoresolve"
}
```

---

### 2.3 Fix Generation Module

**File:** `modules/fix_generator.py`

#### 2.3.1 Responsibilities

| Function | Description |
|----------|-------------|
| `generate_fix_prompt()` | Build LLM prompt with full context |
| `call_llm()` | Request patch from LLM (OpenAI) |
| `parse_diff()` | Extract unified diff from response |
| `validate_syntax()` | AST parse to verify syntactic correctness |
| `validate_diff_applies()` | Test that patch applies cleanly |
| `iterate_on_failure()` | Retry with error feedback |

#### 2.3.2 Fix Generation Pipeline

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  CodeContext    │───▶│   Prompt        │───▶│     LLM         │
│  + ErrorSig     │    │   Builder       │    │   (GPT-4)       │
└─────────────────┘    └─────────────────┘    └────────┬────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │   Raw Response  │
                                              │   (may include  │
                                              │   explanation)  │
                                              └────────┬────────┘
                                                       │
         ┌─────────────────────────────────────────────┼───────┐
         ▼                                             ▼       │
┌─────────────────┐                           ┌─────────────┐  │
│   Diff Parser   │                           │  Syntax     │  │
│   (extract      │                           │  Validator  │  │
│    unified diff)│                           │  (ast.parse)│  │
└────────┬────────┘                           └──────┬──────┘  │
         │                                           │         │
         │            ┌──────────────────────────────┘         │
         ▼            ▼                                        │
┌─────────────────────────────────────┐                        │
│        Patch Application Test       │                        │
│        (git apply --check)          │                        │
└─────────────────┬───────────────────┘                        │
                  │                                             │
         ┌────────┴────────┐                                   │
         ▼                 ▼                                   │
    [SUCCESS]          [FAILURE]───────────────────────────────┘
         │                      (retry with error, max 3x)
         ▼
┌─────────────────┐
│  FixProposal    │
│  (ready for     │
│   security scan)│
└─────────────────┘
```

#### 2.3.3 LLM Fix Prompt

```
You are an expert software engineer fixing a bug. Generate a minimal, focused patch.

## Bug Information
Repository: {repo_full_name}
Error Type: {error_type}
Error Message: {error_message}
Error Signature: {error_signature}

## Stack Trace
{stack_trace}

## Affected Code

### File: {file_path}
```{language}
{function_source}
```

## Issue Description
{issue_body}

## Expected Behavior
{expected_behavior}

## Actual Behavior
{actual_behavior}

## Instructions
1. Analyze the bug and identify the root cause
2. Generate a MINIMAL fix that addresses only this specific issue
3. Do not refactor unrelated code or add new features
4. Ensure the fix handles edge cases mentioned in the issue
5. Output ONLY a unified diff format patch

## Output Format
Respond with ONLY the unified diff, no explanation:

```diff
--- a/{file_path}
+++ b/{file_path}
@@ -line,count +line,count @@
 context line
-removed line
+added line
 context line
```

Generate the patch now:
```

#### 2.3.4 Diff Validation

```python
FUNCTION validate_fix(diff: str, repo_dir: str, language: str) -> FixValidation:
    """
    Validate that the generated diff is syntactically correct and applies cleanly.
    """
    # Step 1: Parse the diff
    TRY:
        parsed = parse_unified_diff(diff)
    EXCEPT DiffParseError as e:
        RETURN FixValidation(valid=False, error="Invalid diff format", details=str(e))
    
    # Step 2: Check diff applies cleanly
    result = subprocess.run(
        ["git", "apply", "--check", "--verbose"],
        input=diff.encode(),
        cwd=repo_dir,
        capture_output=True
    )
    
    IF result.returncode != 0:
        RETURN FixValidation(
            valid=False,
            error="Diff does not apply cleanly",
            details=result.stderr.decode()
        )
    
    # Step 3: Apply diff temporarily and validate syntax
    TRY:
        subprocess.run(["git", "apply"], input=diff.encode(), cwd=repo_dir, check=True)
        
        FOR file_change IN parsed.files:
            file_path = repo_dir / file_change.path

            IF language == "python":
                # Validate Python syntax
                with open(file_path) as f:
                    ast.parse(f.read())
        
        RETURN FixValidation(valid=True, parsed_diff=parsed)
    
    EXCEPT SyntaxError as e:
        RETURN FixValidation(valid=False, error="Syntax error in patched code", details=str(e))
    
    FINALLY:
        # Revert the applied diff
        subprocess.run(["git", "checkout", "."], cwd=repo_dir)
```

#### 2.3.5 Iteration Logic

```python
FUNCTION generate_fix_with_retry(
    context: CodeContext,
    issue: QueuedIssue,
    max_attempts: int = 3
) -> Optional[FixProposal]:
    
    previous_errors = []
    
    FOR attempt IN range(max_attempts):
        # Build prompt with any previous error feedback
        prompt = build_fix_prompt(context, issue, previous_errors)
        
        # Call LLM
        response = call_llm(
            model=FixConfig.llm_model,
            prompt=prompt,
            temperature=FixConfig.llm_temperature + (attempt * 0.1),  # Increase creativity on retry
            max_tokens=FixConfig.max_tokens
        )
        
        # Extract diff from response
        diff = extract_diff(response)
        
        IF NOT diff:
            previous_errors.append("No valid diff found in response")
            CONTINUE
        
        # Validate
        validation = validate_fix(diff, context.repo_dir, context.language)
        
        IF validation.valid:
            RETURN FixProposal(
                issue_id=issue.issue_id,
                repo_full_name=issue.repo_full_name,
                suggested_patch=diff,
                parsed_diff=validation.parsed_diff,
                affected_files=[f.path for f in validation.parsed_diff.files],
                llm_model=FixConfig.llm_model,
                generation_attempts=attempt + 1,
                generated_at=datetime.utcnow()
            )
        ELSE:
            previous_errors.append(f"Attempt {attempt + 1}: {validation.error} - {validation.details}")
    
    # All attempts failed
    log_failure(issue, previous_errors)
    RETURN None
```

#### 2.3.6 Output Schema

```python
FixProposal = {
    "proposal_id": str,             # UUID
    "issue_id": int,
    "repo_full_name": str,
    "suggested_patch": str,         # Unified diff text
    "parsed_diff": ParsedDiff,
    "affected_files": List[str],
    "lines_added": int,
    "lines_removed": int,
    "llm_model": str,
    "generation_attempts": int,
    "generated_at": datetime,
    "status": str                   # "pending_audit" | "audited" | "approved" | "rejected"
}

ParsedDiff = {
    "files": List[FileDiff]
}

FileDiff = {
    "path": str,
    "old_path": Optional[str],      # For renames
    "hunks": List[DiffHunk],
    "is_new": bool,
    "is_deleted": bool
}

DiffHunk = {
    "old_start": int,
    "old_count": int,
    "new_start": int,
    "new_count": int,
    "lines": List[DiffLine]
}

DiffLine = {
    "type": str,                    # "context" | "add" | "remove"
    "content": str,
    "old_lineno": Optional[int],
    "new_lineno": Optional[int]
}
```

#### 2.3.7 Configuration

```python
FixGenerationConfig = {
    "llm_model": "gpt-4",
    "llm_temperature": 0.2,
    "llm_max_tokens": 4096,
    "max_generation_attempts": 3,
    "max_diff_size_lines": 200,
    "context_lines_in_prompt": 50,
    "include_test_files": False,
    "timeout_seconds": 120
}
```

---

### 2.4 Security Audit Module

**File:** `modules/security_auditor.py`

#### 2.4.1 Responsibilities

| Function | Description |
|----------|-------------|
| `run_static_analysis()` | Execute Bandit, Semgrep scans |
| `run_dynamic_analysis()` | Fuzz testing in sandbox (optional) |
| `aggregate_findings()` | Combine results from all scanners |
| `assess_severity()` | Rate vulnerability impact |
| `generate_report()` | Create human-readable security report |

#### 2.4.2 Security Scan Pipeline

```
┌─────────────────┐
│   FixProposal   │
│   (diff + files)│
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    APPLY PATCH TEMPORARILY                  │
└─────────────────────────────┬───────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│     BANDIT      │  │     SEMGREP     │  │   CUSTOM RULES  │
│  (Python SAST)  │  │  (Multi-lang)   │  │   (repo-local)  │
│                 │  │                 │  │                 │
│ • SQL Injection │  │ • XSS           │  │ • Project-spec  │
│ • Command Inj   │  │ • SSRF          │  │   patterns      │
│ • Hardcoded     │  │ • Path Traversal│  │                 │
│   secrets       │  │ • Crypto issues │  │                 │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
                    ┌─────────────────┐
                    │   AGGREGATOR    │
                    │   • Dedupe      │
                    │   • Severity    │
                    │   • Filter FP   │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐         ┌─────────────────┐
                    │   DYNAMIC SCAN  │────────▶│   FUZZ TESTING  │
                    │   (Optional)    │         │   (AFL/pytest)  │
                    └────────┬────────┘         └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  SecurityReport │
                    └─────────────────┘
```

#### 2.4.3 Static Analysis Execution

```python
FUNCTION run_static_analysis(repo_dir: str, affected_files: List[str], language: str) -> List[Finding]:
    findings = []
    
    # Run Bandit for Python
    IF language == "python":
        bandit_result = subprocess.run(
            ["bandit", "-r", "-f", "json", "--exit-zero"] + affected_files,
            cwd=repo_dir,
            capture_output=True
        )
        bandit_findings = parse_bandit_output(bandit_result.stdout)
        findings.extend(bandit_findings)
    
    # Run Semgrep for all languages
    semgrep_result = subprocess.run(
        [
            "semgrep", "scan",
            "--config", "auto",
            "--config", "p/security-audit",
            "--config", "p/owasp-top-ten",
            "--json",
            "--no-git-ignore"
        ] + affected_files,
        cwd=repo_dir,
        capture_output=True
    )
    semgrep_findings = parse_semgrep_output(semgrep_result.stdout)
    findings.extend(semgrep_findings)
    
    # Check for custom rules in repo
    custom_rules_path = repo_dir / ".semgrep.yml"
    IF exists(custom_rules_path):
        custom_result = subprocess.run(
            ["semgrep", "scan", "--config", custom_rules_path, "--json"] + affected_files,
            cwd=repo_dir,
            capture_output=True
        )
        custom_findings = parse_semgrep_output(custom_result.stdout)
        findings.extend(custom_findings)
    
    RETURN deduplicate_findings(findings)
```

#### 2.4.4 Severity Assessment

```python
SEVERITY_WEIGHTS = {
    "critical": 10,
    "high": 7,
    "medium": 4,
    "low": 2,
    "info": 1
}

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

FUNCTION assess_severity(finding: Finding) -> str:
    # Check CWE mapping first
    IF finding.cwe AND finding.cwe IN CWE_SEVERITY_MAP:
        RETURN CWE_SEVERITY_MAP[finding.cwe]
    
    # Fall back to scanner-provided severity
    IF finding.severity:
        RETURN finding.severity.lower()
    
    # Default to medium
    RETURN "medium"

FUNCTION compute_risk_score(findings: List[Finding]) -> float:
    """
    Compute overall risk score (0.0 = safe, 1.0 = critical risk)
    """
    IF NOT findings:
        RETURN 0.0
    
    total_weight = sum(SEVERITY_WEIGHTS[assess_severity(f)] for f in findings)
    max_possible = len(findings) * SEVERITY_WEIGHTS["critical"]
    
    RETURN min(1.0, total_weight / max_possible)
```

#### 2.4.5 Dynamic Analysis (Optional)

```python
FUNCTION run_dynamic_analysis(
    repo_dir: str,
    fix_proposal: FixProposal,
    timeout: int = 300
) -> DynamicScanResult:
    """
    Run fuzz testing on patched code to detect runtime issues.
    """
    # Apply the patch
    subprocess.run(["git", "apply"], input=fix_proposal.suggested_patch.encode(), cwd=repo_dir)
    
    TRY:
        # Detect test framework
        IF exists(repo_dir / "pytest.ini") OR exists(repo_dir / "pyproject.toml"):
            # Run pytest with fuzzing plugin
            result = subprocess.run(
                ["pytest", "--fuzz", "--timeout", str(timeout)],
                cwd=repo_dir,
                capture_output=True,
                timeout=timeout + 30
            )
        ELSE:
            # Basic execution test
            result = subprocess.run(
                ["python", "-m", "py_compile"] + fix_proposal.affected_files,
                cwd=repo_dir,
                capture_output=True,
                timeout=60
            )
        
        RETURN DynamicScanResult(
            passed=result.returncode == 0,
            stdout=result.stdout.decode()[-5000:],
            stderr=result.stderr.decode()[-5000:],
            execution_time=result.duration
        )
    
    EXCEPT TimeoutError:
        RETURN DynamicScanResult(passed=False, error="Timeout during dynamic analysis")
    
    FINALLY:
        # Revert patch
        subprocess.run(["git", "checkout", "."], cwd=repo_dir)
```

#### 2.4.6 Output Schema

```python
Finding = {
    "finding_id": str,              # UUID
    "scanner": str,                 # "bandit" | "semgrep" | "custom"
    "rule_id": str,                 # e.g., "B101", "python.lang.security.audit.exec-used"
    "cwe": Optional[str],           # e.g., "CWE-78"
    "owasp": Optional[str],         # e.g., "A03:2021"
    "severity": str,                # "critical" | "high" | "medium" | "low" | "info"
    "confidence": str,              # "high" | "medium" | "low"
    "file": str,
    "line_start": int,
    "line_end": int,
    "code_snippet": str,
    "message": str,
    "recommendation": Optional[str],
    "false_positive": bool,         # Filtered by heuristics
    "in_new_code": bool             # True if finding is in added lines
}

SecurityReport = {
    "report_id": str,
    "proposal_id": str,
    "has_vulnerabilities": bool,
    "risk_score": float,            # 0.0 - 1.0
    "findings_count": int,
    "findings_by_severity": Dict[str, int],
    "findings": List[Finding],
    "critical_findings": List[Finding],
    "scanners_used": List[str],
    "dynamic_scan_passed": Optional[bool],
    "scan_duration": float,
    "scanned_at": datetime,
    "recommendation": str           # "approve" | "review" | "reject"
}
```

#### 2.4.7 Report Recommendation Logic

```python
FUNCTION generate_recommendation(report: SecurityReport) -> str:
    # Immediate rejection criteria
    IF report.findings_by_severity.get("critical", 0) > 0:
        RETURN "reject"
    
    IF report.findings_by_severity.get("high", 0) > 2:
        RETURN "reject"
    
    # Needs human review
    IF report.findings_by_severity.get("high", 0) > 0:
        RETURN "review"
    
    IF report.findings_by_severity.get("medium", 0) > 3:
        RETURN "review"
    
    IF report.dynamic_scan_passed == False:
        RETURN "review"
    
    IF report.risk_score > 0.3:
        RETURN "review"
    
    # Safe to proceed
    RETURN "approve"
```

#### 2.4.8 Configuration

```python
SecurityAuditConfig = {
    "enabled_scanners": ["bandit", "semgrep"],
    "semgrep_rulesets": ["auto", "p/security-audit", "p/owasp-top-ten"],
    "bandit_severity_threshold": "low",
    "enable_dynamic_scan": False,
    "dynamic_scan_timeout": 300,
    "max_findings_for_approval": 5,
    "auto_reject_severities": ["critical"],
    "false_positive_patterns": [
        r"test_.*\.py",             # Ignore test files
        r".*_test\.py"
    ],
    "timeout_seconds": 180
}
```

---

### 2.5 Approval Module

**File:** `modules/approval.py`

#### 2.5.1 Responsibilities

| Function | Description |
|----------|-------------|
| `post_proposal_comment()` | Add fix summary to GitHub issue |
| `poll_for_approval()` | Check for maintainer response |
| `create_pull_request()` | Open PR with the patch |
| `auto_merge_pr()` | Merge if permissions allow |
| `handle_rejection()` | Process declined proposals |

#### 2.5.2 Approval Workflow

```
┌─────────────────┐
│ SecurityReport  │
│ (recommendation)│
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                 POST COMMENT TO ISSUE                       │
│                                                             │
│  🤖 AutoResolve has analyzed this issue.                   │
│                                                             │
│  **Reproduction:** ✅ Confirmed                             │
│  **Proposed Fix:** Available                                │
│  **Security Scan:** ✅ Passed (0 critical, 0 high)         │
│                                                             │
│  <details>                                                  │
│  <summary>View Proposed Patch</summary>                     │
│  ```diff                                                    │
│  --- a/auth/login.py                                        │
│  +++ b/auth/login.py                                        │
│  @@ -55,7 +55,7 @@                                          │
│  -    user = get_user(None)                                 │
│  +    user = get_user(username)                             │
│  ```                                                        │
│  </details>                                                 │
│                                                             │
│  **To approve:** Reply with `@autoresolve approve` or 👍   │
│  **To reject:** Reply with `@autoresolve reject`           │
│  **To request changes:** Describe what you'd like changed  │
│                                                             │
│  ⏱️ This proposal expires in 7 days.                       │
└─────────────────────────────────┬───────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │   POLL FOR RESPONSE     │
                    │   (every 5 minutes)     │
                    └─────────────┬───────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    APPROVED     │     │    REJECTED     │     │   TIMED OUT     │
│                 │     │                 │     │   (7 days)      │
│ • Create PR     │     │ • Log reason    │     │                 │
│ • Auto-merge    │     │ • Close         │     │ • Notify owner  │
│   (if allowed)  │     │   proposal      │     │ • Archive       │
│ • Notify        │     │ • Notify        │     │                 │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │   UPDATE DATABASE       │
                    │   EMIT EVENT            │
                    └─────────────────────────┘
```

#### 2.5.3 Comment Template

```python
APPROVAL_COMMENT_TEMPLATE = """
## 🤖 AutoResolve Analysis Complete

| Check | Status |
|-------|--------|
| **Reproduction** | {reproduction_status} |
| **Fix Generated** | {fix_status} |
| **Security Scan** | {security_status} |

### Proposed Fix

<details>
<summary>Click to view diff ({lines_changed} lines changed)</summary>

```diff
{diff}
```

</details>

### Security Report

{security_summary}

---

### Actions

| Command | Description |
|---------|-------------|
| `@autoresolve approve` | Create PR and merge |
| `@autoresolve approve --no-merge` | Create PR only |
| `@autoresolve reject` | Decline this fix |
| `@autoresolve regenerate` | Generate a new fix |
| 👍 reaction | Same as approve |
| 👎 reaction | Same as reject |

⏱️ **Expires:** {expiry_date} ({days_remaining} days)

---
<sub>AutoResolve v{version} • [Documentation]({docs_url}) • [Report Issue]({report_url})</sub>
"""
```

#### 2.5.4 Response Polling

```python
FUNCTION poll_for_approval(issue_id: int, repo: str, proposal: FixProposal) -> ApprovalResult:
    """
    Poll issue comments for maintainer response.
    Called every 5 minutes by Celery beat until resolved or expired.
    """
    # Get issue comments since proposal was posted
    comments = github_api.get_issue_comments(
        repo=repo,
        issue_number=issue_id,
        since=proposal.generated_at
    )
    
    # Get issue reactions
    reactions = github_api.get_issue_reactions(
        repo=repo,
        issue_number=issue_id,
        content=["thumbs_up", "thumbs_down"]
    )
    
    # Check for approval
    FOR comment IN comments:
        # Only accept from maintainers
        IF NOT is_maintainer(comment.author, repo):
            CONTINUE
        
        text = comment.body.lower()
        
        IF "@autoresolve approve" IN text:
            no_merge = "--no-merge" IN text
            RETURN ApprovalResult(
                status="approved",
                approved_by=comment.author,
                auto_merge=NOT no_merge,
                approved_at=comment.created_at
            )
        
        IF "@autoresolve reject" IN text:
            RETURN ApprovalResult(
                status="rejected",
                rejected_by=comment.author,
                rejection_reason=extract_reason(comment.body),
                rejected_at=comment.created_at
            )
        
        IF "@autoresolve regenerate" IN text:
            RETURN ApprovalResult(
                status="regenerate",
                requested_by=comment.author,
                feedback=extract_feedback(comment.body)
            )
    
    # Check reactions from maintainers
    FOR reaction IN reactions:
        IF is_maintainer(reaction.user, repo):
            IF reaction.content == "thumbs_up":
                RETURN ApprovalResult(status="approved", approved_by=reaction.user)
            IF reaction.content == "thumbs_down":
                RETURN ApprovalResult(status="rejected", rejected_by=reaction.user)
    
    # Check expiry
    IF datetime.utcnow() > proposal.generated_at + timedelta(days=ApprovalConfig.timeout_days):
        RETURN ApprovalResult(status="expired")
    
    RETURN ApprovalResult(status="pending")
```

#### 2.5.5 Pull Request Creation

```python
FUNCTION create_pull_request(proposal: FixProposal, approval: ApprovalResult) -> PullRequest:
    """
    Create a PR with the approved patch.
    """
    repo = proposal.repo_full_name
    base_branch = get_default_branch(repo)
    
    # Create branch
    branch_name = f"autoresolve/fix-{proposal.issue_id}-{generate_short_id()}"
    
    github_api.create_branch(
        repo=repo,
        branch=branch_name,
        from_ref=base_branch
    )
    
    # Apply patch via GitHub API
    FOR file_diff IN proposal.parsed_diff.files:
        current_content = github_api.get_file_contents(repo, file_diff.path, base_branch)
        new_content = apply_diff_to_content(current_content, file_diff)
        
        github_api.update_file(
            repo=repo,
            path=file_diff.path,
            content=new_content,
            branch=branch_name,
            message=f"fix: resolve issue #{proposal.issue_id}\n\nAutomated fix by AutoResolve"
        )
    
    # Create PR
    pr = github_api.create_pull_request(
        repo=repo,
        title=f"fix: {get_issue_title(proposal.issue_id)} (#{proposal.issue_id})",
        body=generate_pr_body(proposal, approval),
        head=branch_name,
        base=base_branch
    )
    
    # Link to issue
    github_api.add_issue_comment(
        repo=repo,
        issue_number=proposal.issue_id,
        body=f"✅ Pull request created: #{pr.number}"
    )
    
    # Auto-merge if requested and allowed
    IF approval.auto_merge AND can_auto_merge(repo):
        TRY:
            wait_for_checks(pr.number, timeout=300)
            github_api.merge_pull_request(
                repo=repo,
                pr_number=pr.number,
                merge_method="squash"
            )
            github_api.close_issue(repo, proposal.issue_id)
        EXCEPT ChecksFailedError:
            github_api.add_pr_comment(pr.number, "⚠️ Auto-merge skipped: CI checks failed")
    
    RETURN pr
```

#### 2.5.6 PR Body Template

```python
PR_BODY_TEMPLATE = """
## Summary

Automated fix for #{issue_number}: {issue_title}

## Changes

{diff_summary}

## Validation

- ✅ Issue reproduced in sandbox
- ✅ Patch applies cleanly
- ✅ Syntax validation passed
- {security_status}

## Security Scan Results

| Severity | Count |
|----------|-------|
| Critical | {critical} |
| High | {high} |
| Medium | {medium} |
| Low | {low} |

## Approval

Approved by @{approved_by} on {approved_at}

---

<sub>🤖 Generated by [AutoResolve](https://github.com/yourorg/autoresolve) v{version}</sub>

Closes #{issue_number}
"""
```

#### 2.5.7 Output Schema

```python
ApprovalResult = {
    "status": str,                  # "pending" | "approved" | "rejected" | "expired" | "regenerate"
    "approved_by": Optional[str],
    "rejected_by": Optional[str],
    "auto_merge": bool,
    "rejection_reason": Optional[str],
    "feedback": Optional[str],      # For regenerate requests
    "resolved_at": Optional[datetime]
}

PullRequestResult = {
    "pr_number": int,
    "pr_url": str,
    "branch_name": str,
    "status": str,                  # "open" | "merged" | "closed"
    "checks_passed": Optional[bool],
    "merged_at": Optional[datetime],
    "merged_by": Optional[str]
}
```

#### 2.5.8 Configuration

```python
ApprovalConfig = {
    "timeout_days": 7,
    "poll_interval_minutes": 5,
    "require_maintainer": True,
    "auto_merge_enabled": True,
    "auto_merge_wait_for_checks": True,
    "auto_merge_method": "squash",
    "branch_prefix": "autoresolve/fix-",
    "pr_labels": ["automated", "autoresolve"],
    "close_issue_on_merge": True
}
```

---

## 3. Data Models

### 3.1 Database Schema (PostgreSQL)

```sql
-- Issues table
CREATE TABLE issues (
    id SERIAL PRIMARY KEY,
    queue_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    github_issue_id INTEGER NOT NULL,
    repo_full_name VARCHAR(255) NOT NULL,
    repo_url TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    labels JSONB DEFAULT '[]',
    author VARCHAR(100),
    github_created_at TIMESTAMP WITH TIME ZONE,
    queued_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    priority INTEGER DEFAULT 3,
    status VARCHAR(50) DEFAULT 'pending',
    
    UNIQUE(repo_full_name, github_issue_id),
    INDEX idx_issues_status (status),
    INDEX idx_issues_repo (repo_full_name),
    INDEX idx_issues_priority (priority)
);

-- Validation results
CREATE TABLE validations (
    id SERIAL PRIMARY KEY,
    issue_id INTEGER REFERENCES issues(id) ON DELETE CASCADE,
    valid BOOLEAN NOT NULL,
    validity_status VARCHAR(50),
    match_score FLOAT,
    error_signature TEXT,
    issue_context JSONB,
    reproduction_result JSONB,
    code_context JSONB,
    sandbox_image VARCHAR(100),
    validated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    validation_duration FLOAT,
    
    INDEX idx_validations_issue (issue_id)
);

-- Fix proposals
CREATE TABLE fix_proposals (
    id SERIAL PRIMARY KEY,
    proposal_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    issue_id INTEGER REFERENCES issues(id) ON DELETE CASCADE,
    validation_id INTEGER REFERENCES validations(id),
    suggested_patch TEXT NOT NULL,
    parsed_diff JSONB,
    affected_files JSONB DEFAULT '[]',
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,
    llm_model VARCHAR(100),
    generation_attempts INTEGER DEFAULT 1,
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'pending_audit',
    
    INDEX idx_proposals_issue (issue_id),
    INDEX idx_proposals_status (status)
);

-- Security reports
CREATE TABLE security_reports (
    id SERIAL PRIMARY KEY,
    report_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    proposal_id INTEGER REFERENCES fix_proposals(id) ON DELETE CASCADE,
    has_vulnerabilities BOOLEAN NOT NULL,
    risk_score FLOAT,
    findings_count INTEGER DEFAULT 0,
    findings_by_severity JSONB DEFAULT '{}',
    findings JSONB DEFAULT '[]',
    scanners_used JSONB DEFAULT '[]',
    dynamic_scan_passed BOOLEAN,
    recommendation VARCHAR(50),
    scanned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    scan_duration FLOAT,
    
    INDEX idx_security_proposal (proposal_id)
);

-- Approvals
CREATE TABLE approvals (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES fix_proposals(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL,
    approved_by VARCHAR(100),
    rejected_by VARCHAR(100),
    auto_merge BOOLEAN DEFAULT TRUE,
    rejection_reason TEXT,
    comment_id BIGINT,
    pr_number INTEGER,
    pr_url TEXT,
    pr_merged BOOLEAN,
    resolved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    INDEX idx_approvals_proposal (proposal_id),
    INDEX idx_approvals_status (status)
);

-- Audit log
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    event_type VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50),
    entity_id INTEGER,
    actor VARCHAR(100),
    details JSONB,
    
    INDEX idx_audit_timestamp (timestamp),
    INDEX idx_audit_entity (entity_type, entity_id)
);

-- Monitored repositories
CREATE TABLE monitored_repos (
    id SERIAL PRIMARY KEY,
    repo_full_name VARCHAR(255) UNIQUE NOT NULL,
    webhook_id BIGINT,
    webhook_secret VARCHAR(255),
    enabled BOOLEAN DEFAULT TRUE,
    settings JSONB DEFAULT '{}',
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_polled_at TIMESTAMP WITH TIME ZONE,
    
    INDEX idx_repos_enabled (enabled)
);
```

### 3.2 Redis Keys

```python
REDIS_KEYS = {
    # Rate limiting
    "rate_limit:github:{endpoint}": "Remaining API calls (TTL: 1 hour)",
    "rate_limit:llm:tokens": "Token usage tracking (TTL: 1 day)",
    
    # Deduplication
    "processed:{repo}:{issue_id}": "Issue processing lock (TTL: 24 hours)",
    
    # Caching
    "cache:maintainers:{repo}": "List of repo maintainers (TTL: 1 hour)",
    "cache:default_branch:{repo}": "Default branch name (TTL: 6 hours)",
    
    # Queue management
    "queue:pending": "Sorted set of pending issues by priority",
    "queue:processing": "Set of currently processing issue IDs",
    
    # Session data
    "session:validation:{issue_id}": "Validation state (TTL: 1 hour)",
    "session:sandbox:{container_id}": "Sandbox container info (TTL: 30 min)"
}
```

---

## 4. API Specification

### 4.1 Webhook Endpoint

```
POST /webhook/github
Content-Type: application/json
X-Hub-Signature-256: sha256=...
X-GitHub-Event: issues

Response: 200 OK | 400 Bad Request | 401 Unauthorized
```

### 4.2 Management API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/health` | Health check | None |
| GET | `/api/repos` | List monitored repos | API Key |
| POST | `/api/repos` | Add repo to monitor | API Key |
| DELETE | `/api/repos/{repo}` | Remove repo | API Key |
| GET | `/api/issues` | List processed issues | API Key |
| GET | `/api/issues/{id}` | Get issue details | API Key |
| GET | `/api/proposals/{id}` | Get fix proposal | API Key |
| POST | `/api/proposals/{id}/retry` | Regenerate fix | API Key |
| GET | `/api/reports/{id}` | Get security report | API Key |
| GET | `/api/stats` | System statistics | API Key |

### 4.3 Request/Response Examples

```python
# Add repository
POST /api/repos
{
    "repo_full_name": "org/repo",
    "settings": {
        "auto_merge": true,
        "security_threshold": "high"
    }
}

Response 201:
{
    "id": 1,
    "repo_full_name": "org/repo",
    "webhook_id": 12345678,
    "enabled": true,
    "added_at": "2026-01-09T12:00:00Z"
}

# Get issue status
GET /api/issues/42

Response 200:
{
    "id": 42,
    "github_issue_id": 532,
    "repo_full_name": "org/repo",
    "title": "TypeError in login function",
    "status": "fix_proposed",
    "validation": {
        "valid": true,
        "match_score": 0.92
    },
    "proposal": {
        "proposal_id": "abc-123",
        "affected_files": ["auth/login.py"],
        "security_status": "passed"
    },
    "approval": {
        "status": "pending",
        "expires_at": "2026-01-16T12:00:00Z"
    }
}
```

---

## 5. Task Queue Configuration

### 5.1 Celery Tasks

```python
# tasks.py

@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def process_issue(self, issue_id: int):
    """Main processing pipeline for an issue."""
    try:
        issue = get_issue(issue_id)
        
        # Step 1: Validate
        validation = validate_issue(issue)
        save_validation(issue_id, validation)
        
        if not validation.valid:
            close_as_invalid(issue)
            return
        
        # Step 2: Generate fix
        proposal = generate_fix(issue, validation)
        if not proposal:
            mark_as_unfixable(issue)
            return
        save_proposal(issue_id, proposal)
        
        # Step 3: Security audit
        report = run_security_audit(proposal)
        save_security_report(proposal.id, report)
        
        if report.recommendation == "reject":
            mark_as_security_risk(issue, report)
            return
        
        # Step 4: Request approval
        post_approval_comment(issue, proposal, report)
        schedule_approval_polling(issue_id, proposal.id)
        
    except Exception as e:
        self.retry(exc=e)


@celery.task
def poll_approval(proposal_id: int):
    """Check for maintainer response."""
    proposal = get_proposal(proposal_id)
    result = check_for_approval(proposal)
    
    if result.status == "approved":
        create_and_merge_pr.delay(proposal_id, result)
    elif result.status == "rejected":
        handle_rejection(proposal, result)
    elif result.status == "expired":
        handle_expiry(proposal)
    elif result.status == "pending":
        # Re-schedule check
        poll_approval.apply_async(args=[proposal_id], countdown=300)


@celery.task
def create_and_merge_pr(proposal_id: int, approval: ApprovalResult):
    """Create PR and optionally merge."""
    proposal = get_proposal(proposal_id)
    pr = create_pull_request(proposal, approval)
    
    if approval.auto_merge:
        wait_and_merge(pr)


@celery.task
def poll_repositories():
    """Fallback polling for missed webhooks."""
    repos = get_enabled_repos()
    for repo in repos:
        issues = poll_repo_issues(repo)
        for issue in issues:
            process_issue.delay(issue.id)


# Celery beat schedule
CELERYBEAT_SCHEDULE = {
    "poll-repos": {
        "task": "tasks.poll_repositories",
        "schedule": crontab(minute="*/5")
    },
    "cleanup-expired": {
        "task": "tasks.cleanup_expired_proposals",
        "schedule": crontab(hour=0, minute=0)
    }
}
```

### 5.2 Queue Configuration

```python
CELERY_CONFIG = {
    "broker_url": "amqp://guest:guest@localhost:5672//",
    "result_backend": "redis://localhost:6379/0",
    "task_serializer": "json",
    "result_serializer": "json",
    "accept_content": ["json"],
    "timezone": "UTC",
    "task_routes": {
        "tasks.process_issue": {"queue": "processing"},
        "tasks.poll_approval": {"queue": "polling"},
        "tasks.create_and_merge_pr": {"queue": "github"},
        "tasks.poll_repositories": {"queue": "polling"}
    },
    "task_annotations": {
        "tasks.process_issue": {"rate_limit": "10/m"},
        "tasks.create_and_merge_pr": {"rate_limit": "30/m"}
    }
}
```

---

## 6. Configuration

### 6.1 Master Configuration File

**File:** `config.yaml`

```yaml
# AutoResolve Configuration

# Application
app:
  name: "AutoResolve"
  version: "1.0.0"
  debug: false
  secret_key: "${APP_SECRET_KEY}"

# GitHub Integration
github:
  app_id: ${GITHUB_APP_ID}
  private_key_path: "/secrets/github-app.pem"
  webhook_secret: "${GITHUB_WEBHOOK_SECRET}"
  api_base_url: "https://api.github.com"
  rate_limit_buffer: 100

# Monitored Repositories (can also be managed via API)
monitored_repos:
  - "org/repo1"
  - "org/repo2"

# Filtering
filtering:
  trigger_labels:
    - "bug"
    - "error"
    - "defect"
  exclude_labels:
    - "wontfix"
    - "duplicate"
  exclude_authors:
    - "dependabot"
    - "renovate"
  min_body_length: 50
  max_age_days: 30

# Validation
validation:
  sandbox_timeout_seconds: 300
  sandbox_memory_limit: "512m"
  sandbox_network: "none"
  clone_depth: 1
  min_match_score: 0.6

# Fix Generation
fix_generation:
  llm_provider: "openai"
  llm_model: "gpt-4"
  llm_temperature: 0.2
  max_attempts: 3
  max_diff_lines: 200
  timeout_seconds: 120

# Security Audit
security:
  enabled_scanners:
    - "bandit"
    - "semgrep"
  semgrep_rulesets:
    - "auto"
    - "p/security-audit"
    - "p/owasp-top-ten"
  enable_dynamic_scan: false
  auto_reject_severities:
    - "critical"

# Approval
approval:
  timeout_days: 7
  poll_interval_minutes: 5
  require_maintainer: true
  auto_merge_enabled: true
  auto_merge_method: "squash"

# Database
database:
  url: "postgresql://autoresolve:${DB_PASSWORD}@localhost:5432/autoresolve"
  pool_size: 10

# Redis
redis:
  url: "redis://localhost:6379/0"

# Celery
celery:
  broker_url: "amqp://guest:guest@localhost:5672//"
  result_backend: "redis://localhost:6379/1"

# API
api:
  host: "0.0.0.0"
  port: 8000
  api_key: "${API_KEY}"

# Logging
logging:
  level: "INFO"
  format: "json"
  output: "stdout"
```

---

## 7. Directory Structure

```
autoresolve/
│
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application
│   ├── config.py                   # Configuration loader
│   └── dependencies.py             # DI container
│
├── modules/
│   ├── __init__.py
│   ├── monitoring.py               # Webhook + polling
│   ├── validation.py               # Issue reproduction
│   ├── fix_generator.py            # LLM patch generation
│   ├── security_auditor.py         # SAST/DAST scanning
│   └── approval.py                 # PR creation + merge
│
├── api/
│   ├── __init__.py
│   ├── routes/
│   │   ├── webhook.py
│   │   ├── repos.py
│   │   ├── issues.py
│   │   └── proposals.py
│   └── middleware/
│       ├── auth.py
│       └── logging.py
│
├── tasks/
│   ├── __init__.py
│   ├── celery_app.py
│   ├── processing.py
│   └── polling.py
│
├── models/
│   ├── __init__.py
│   ├── database.py                 # SQLAlchemy models
│   ├── schemas.py                  # Pydantic models
│   └── compat.py                   # Cross-database JSON type
│
├── services/
│   ├── __init__.py
│   ├── github_service.py
│   ├── llm_service.py
│   └── docker_service.py
│
├── utils/
│   ├── __init__.py
│   ├── diff_parser.py
│   ├── signature.py
│   └── logging.py
│
├── templates/
│   ├── comments/
│   │   ├── approval_request.md
│   │   ├── rejection.md
│   │   └── pr_body.md
│   └── prompts/
│       ├── issue_parser.txt
│       └── fix_generator.txt
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_monitoring.py
│   ├── test_validation.py
│   ├── test_fix_generator.py
│   ├── test_security.py
│   ├── test_approval.py
│   └── fixtures/
│       ├── sample_issues.json
│       └── sample_diffs.txt
│
├── migrations/
│   └── versions/
│
├── docker/
│   ├── Dockerfile
│   ├── Dockerfile.worker
│   └── sandbox/
│       └── Dockerfile.python
│
├── scripts/
│   ├── setup_github_app.py
│   └── seed_test_data.py
│
├── config.yaml
├── requirements.txt
├── docker-compose.yaml
├── Makefile
└── README.md
```

---

## 8. Testing Strategy

### 8.1 Test Matrix

| Test Type | Tool | Target | Coverage Goal |
|-----------|------|--------|---------------|
| Unit | pytest | All modules | ≥ 90% |
| Integration | pytest | End-to-end pipeline | ≥ 80% |
| API | pytest-httpx | REST endpoints | 100% |
| Security | bandit | Codebase | 0 high/critical |

### 8.2 Key Test Scenarios

```python
# test_validation.py

def test_valid_issue_reproduction():
    """Confirm valid issues are correctly reproduced."""
    issue = create_test_issue(
        title="TypeError in auth module",
        body="```\nTraceback:\n  File auth.py, line 42\nTypeError: NoneType\n```"
    )
    result = validate_issue(issue)
    
    assert result.valid == True
    assert result.match_score >= 0.8
    assert "TypeError" in result.error_signature


def test_invalid_issue_not_reproduced():
    """Confirm invalid issues are correctly rejected."""
    issue = create_test_issue(
        title="Please add dark mode",
        body="Would be nice to have dark mode support."
    )
    result = validate_issue(issue)
    
    assert result.valid == False
    assert result.validity_status == "not_reproduced"


def test_security_scanner_detects_injection():
    """Confirm security scanner catches SQL injection."""
    diff = """
    --- a/db.py
    +++ b/db.py
    @@ -10,7 +10,7 @@
    -    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    +    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
    """
    
    report = run_security_audit(create_proposal(diff))
    
    assert report.has_vulnerabilities == True
    assert any(f.cwe == "CWE-89" for f in report.findings)
    assert report.recommendation == "reject"
```

### 8.3 Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Webhook latency (p99) | < 500ms | Time from receive to queue |
| Validation duration | < 5 min | Sandbox execution time |
| Fix generation latency | < 2 min | LLM response time |
| Security scan duration | < 3 min | All scanners complete |
| End-to-end (issue → PR) | < 15 min | Full pipeline |
| False positive rate | < 10% | Fixes that don't resolve issue |
| Security false negative | < 5% | Vulnerabilities missed |

---

## 9. Deployment

### 9.1 Docker Compose (Development)

```yaml
version: "3.9"

services:
  api:
    build:
      context: .
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://autoresolve:password@postgres:5432/autoresolve
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
      - GITHUB_APP_ID=${GITHUB_APP_ID}
      - GITHUB_WEBHOOK_SECRET=${GITHUB_WEBHOOK_SECRET}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./secrets:/secrets:ro
    depends_on:
      - postgres
      - redis
      - rabbitmq

  worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    environment:
      - DATABASE_URL=postgresql://autoresolve:password@postgres:5432/autoresolve
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # For sandbox containers
      - ./config.yaml:/app/config.yaml
      - ./secrets:/secrets:ro
    depends_on:
      - postgres
      - redis
      - rabbitmq

  beat:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    command: celery -A tasks beat --loglevel=info
    environment:
      - CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
    depends_on:
      - rabbitmq

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: autoresolve
      POSTGRES_PASSWORD: password
      POSTGRES_DB: autoresolve
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  rabbitmq:
    image: rabbitmq:3-management
    ports:
      - "5672:5672"
      - "15672:15672"

volumes:
  postgres_data:
```

### 9.2 Production Architecture

```
                    ┌─────────────────────────────────────┐
                    │           Load Balancer             │
                    │         (AWS ALB / nginx)           │
                    └─────────────────┬───────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐
│   API Server    │          │   API Server    │          │   API Server    │
│   (Fargate)     │          │   (Fargate)     │          │   (Fargate)     │
└────────┬────────┘          └────────┬────────┘          └────────┬────────┘
         │                            │                            │
         └────────────────────────────┼────────────────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐
│  Worker Pool    │          │   RabbitMQ      │          │   Redis         │
│  (ECS/K8s)      │◀────────▶│   (Amazon MQ)   │          │  (ElastiCache)  │
└────────┬────────┘          └─────────────────┘          └─────────────────┘
         │
         ▼
┌─────────────────┐          ┌─────────────────┐
│  PostgreSQL     │          │   S3 Artifacts  │
│  (RDS)          │          │   (Logs, Diffs) │
└─────────────────┘          └─────────────────┘
```

### 9.3 CI/CD Pipeline

```yaml
# .github/workflows/deploy.yaml

name: Deploy AutoResolve

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: |
          pip install -r requirements.txt
          pytest --cov=app --cov-report=xml
      - name: Security scan
        run: |
          bandit -r app/
          safety check

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build and push
        run: |
          docker build -t autoresolve:${{ github.sha }} .
          docker push $ECR_REPO:${{ github.sha }}

  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster autoresolve \
            --service api \
            --force-new-deployment
```

---

## 10. Dependencies

### 10.1 Python Requirements

```
# Core
python-multipart>=0.0.6
fastapi>=0.109
uvicorn>=0.27
pydantic>=2.5
pydantic-settings>=2.1

# Database
sqlalchemy>=2.0
psycopg2-binary>=2.9
alembic>=1.13

# Task Queue
celery>=5.3
amqp>=5.2

# Redis
redis>=5.0

# LLM
openai>=1.0
tiktoken>=0.5

# Security Scanning
bandit>=1.7

# Docker
docker>=7.0

# HTTP
requests>=2.31
httpx>=0.26

# Parsing
unidiff>=0.7

# Utilities
python-dotenv>=1.0
pyyaml>=6.0
jinja2>=3.1

# Testing
pytest>=7.4
pytest-asyncio>=0.23
pytest-cov>=4.1
pytest-httpx>=0.28

# Structured Logging
structlog>=24.1
```

### 10.2 External Tools

| Tool | Version | Purpose |
|------|---------|---------|
| Semgrep | latest | Python SAST with OWASP rules |
| Bandit | 1.7+ | Python SAST |
| Docker | 24+ | Sandbox isolation |
| PostgreSQL | 16 | Primary database |
| Redis | 7+ | Caching, rate limiting |
| RabbitMQ | 3.12+ | Task queue broker |

---

## 11. Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| GitHub API rate limiting | High | Medium | Exponential backoff, caching, webhook preference |
| False positive fixes | Medium | High | Require maintainer approval, never auto-merge by default |
| Security sandbox escape | Low | Critical | Network isolation, resource limits, read-only mounts |
| LLM generates vulnerable code | Medium | High | Mandatory security scan, block critical findings |
| Webhook replay attacks | Low | Medium | Signature verification, idempotency keys |
| Cost overrun (LLM tokens) | Medium | Medium | Token budgets, caching, rate limiting |

---

## 12. Future Extensions

| Extension | Description | Priority |
|-----------|-------------|----------|
| **Learning Loop** | Fine-tune fix generation from merged PRs | High |
| **Auto-Labeling** | NLP classifier to tag new issues | Medium |
| **PR Quality Scoring** | LLM-based code review agent | Medium |
| **Multi-repo Analysis** | Detect similar bugs across repos | Medium |
| **Integration Marketplace** | Slack, Discord, Jira, Notion connectors | Low |
| **NatLangChain Bridge** | Reasoning chains for complex root-cause analysis | High |
| **Self-hosted LLM** | Ollama/vLLM for air-gapped deployments | Low |

---

*Specification complete. Ready for implementation.*
