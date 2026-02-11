# AutoResolve Refocus Plan

**Date:** 2026-02-11
**Based on:** EVALUATION_REPORT.md (Concept-Execution-Evaluation framework)
**Goal:** Strip to Python-only, fix broken foundations, harden core pipeline, ship against real repos.

---

## Evaluation Correction

The evaluation report incorrectly stated that `app/dependencies.py` doesn't exist. It does exist and correctly exports `get_db`. The `conftest.py:65` import is valid. The remaining test infrastructure issues (JSONB/SQLite mismatch, deprecated `datetime.utcnow()`) are still critical.

---

## Phase 1: CUT — Remove Dead Weight

**Objective:** Eliminate code that inflates perceived capability without delivering value. Reduce surface area, reduce dependencies, reduce cognitive load.

### 1.1 Remove Multi-Language Support

Strip Go, Rust, Java, and Node/JavaScript/TypeScript code paths. AutoResolve doesn't genuinely support these — issue parsing is Python-focused, function extraction only works for Python, and the LLM prompt doesn't vary by language.

**Files to delete:**
- `docker/sandbox/Dockerfile.node` — Node.js sandbox image (54 lines, not needed)
- `utils/language_detector.py` — Standalone language detector with 8+ languages. Replace all call sites with hardcoded `"python"` or a trivial Python-only check.

**Files to edit:**

| File | Lines | Change |
|------|-------|--------|
| `modules/validation.py` | 77-90 | `SANDBOX_IMAGES` — Remove node/go/rust/java entries, keep only python |
| `modules/validation.py` | 93-103 | `DEFAULT_TEST_COMMANDS` — Remove node/go/rust/java entries |
| `modules/validation.py` | 107-115 | `ALLOWED_COMMAND_PREFIXES` — Remove node/npm/npx/yarn/go/cargo/rustc/mvn/gradle/java/javac |
| `modules/validation.py` | 280-284 | Error patterns — Remove `NullPointerException`, `IndexOutOfBoundsException`, `SegmentationFault` regexes |
| `modules/validation.py` | 295-297 | File path regexes — Remove `.js`, `.ts`, `.go`, `.rs`, `.java` extensions |
| `modules/validation.py` | 383-419 | `detect_language()` — Simplify to always return `"python"` (or detect Python indicators, default to Python) |
| `modules/validation.py` | 709 | `_is_code_file()` — Keep only `.py` |
| `modules/validation.py` | 771-792 | `_get_test_command()` — Remove non-Python branches |
| `modules/fix_generator.py` | 421-500 | `validate_fix()` — Delete the `elif language in ("javascript"...` through Java blocks. Keep only Python AST validation. |
| `app/config.py` | 79-81 | `FilterConfig.trigger_keywords` — Remove `NullPointerException`, `IndexOutOfBounds`, `SegmentationFault` |
| `app/config.py` | 148 | `FixGenerationConfig` — Remove `java_compile_timeout` field |

**Test files to update:**
- `tests/test_validation.py` — Remove `test_detects_javascript()` and `test_detects_go()` tests
- `tests/fixtures/sample_issues.json` — Remove JavaScript and Java test case entries

### 1.2 Remove Notification Service

Disabled by default, untested, and not needed until production deployment.

**Files to delete:**
- `services/notification_service.py` — 251 lines of Slack/email notification code

**Files to edit:**

| File | Lines | Change |
|------|-------|--------|
| `modules/approval.py` | 663-700 | Delete `notify_stakeholders()` function entirely |
| `app/config.py` | 184-197 | Delete `NotificationConfig` class |
| `app/config.py` | 273 | Remove `notifications: NotificationConfig` from `Settings` |
| `app/config.py` | 323-327 | Remove notifications from `_merge_yaml_config` |
| `app/config.py` | 335-366 | Delete `_merge_notification_config()` method |
| `config.yaml` | 77-87 | Delete entire `notifications:` section |
| `services/__init__.py` | | Remove notification_service references in docstring |

### 1.3 Remove Observability Plumbing

Sentry and Prometheus are configured but never initialized or imported anywhere in the code. Remove the config and dependencies.

**Files to edit:**

| File | Lines | Change |
|------|-------|--------|
| `app/config.py` | 252-259 | Delete `ObservabilityConfig` class |
| `app/config.py` | 279 | Remove `observability: ObservabilityConfig` from `Settings` |
| `app/config.py` | 313 | Remove `"observability"` from `config_mapping` |
| `config.yaml` | 114-118 | Delete `observability:` section |

**Keep:** `structlog` — it's actively used for JSON-structured logging in `utils/logging.py`.

### 1.4 Trim Dependencies

**Remove from `requirements.txt`:**
- `sentry-sdk>=1.39` — Never imported
- `prometheus-client>=0.19` — Never imported
- `locust>=2.20` — No load test files exist
- `spacy>=3.7` — Spec mentions spaCy NER fallback but code uses regex (`_fallback_parse`). spaCy is never imported.
- `PyGithub>=2.1` — Never imported; all GitHub API calls use `httpx` via `GitHubService`

**Keep:**
- `structlog>=24.1` — Actively used
- `gitpython>=3.1` — Review if used (may only be needed for future features)

---

## Phase 2: FIX FOUNDATIONS — Make Tests Real

**Objective:** Fix broken infrastructure so tests actually prove something. This is the single highest-impact change.

### 2.1 Fix JSONB/SQLite Test Incompatibility

**Problem:** Models use `JSONB` (PostgreSQL-specific). Tests use SQLite in-memory. SQLAlchemy will silently fall back, but behavior differs and table creation may fail.

**Solution:** Create a cross-database compatible JSON type:

```python
# models/compat.py (new file)
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator
import json

class JSONType(TypeDecorator):
    """JSON type that works with both PostgreSQL (JSONB) and SQLite (TEXT)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return value

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(Text())
```

**Then in `models/database.py`:** Replace all `JSONB` imports and usages with `JSONType`.

### 2.2 Fix Mutable Default Values

**Problem:** `default=list` and `default=dict` in SQLAlchemy columns share mutable objects across instances.

**Fix:** Change all occurrences in `models/database.py`:

| Line | Before | After |
|------|--------|-------|
| 59 | `default=list` | `default=list` (this is actually OK in SQLAlchemy mapped_column — it calls the callable) |

**Verification needed:** Confirm SQLAlchemy 2.0's `mapped_column` treats `list` and `dict` as callables (factory functions). If so, no change needed. If not, change to `default_factory=list`.

### 2.3 Fix Deprecated `datetime.utcnow()` in Tests

**Problem:** Tests use `datetime.utcnow()` which returns naive datetimes. Models use `DateTime(timezone=True)`. Python 3.12+ deprecates `utcnow()`.

**Fix:** Replace all `datetime.utcnow()` with `datetime.now(timezone.utc)` in:
- `tests/conftest.py:138`
- `tests/test_approval.py` (lines 148, 162, 181, 195, 222)
- `tests/test_monitoring.py` (lines 27, 40, 53, 61, 80, 93, 106)
- `scripts/seed_test_data.py` (lines 235, 268, 269, 300, 321, 322)

### 2.4 Cache Database Engine

**Problem:** `get_engine()` calls `create_engine()` on every invocation. `get_session_factory()` calls `get_engine()` on every invocation. In Celery workers, this creates a new engine per task, wasting connection pool benefits.

**Fix in `models/database.py`:**

```python
_engine = None
_session_factory = None

def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database.url,
            pool_size=settings.database.pool_size,
            pool_pre_ping=True,
        )
    return _engine

def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine())
    return _session_factory
```

### 2.5 Fix Celery Async Anti-Pattern

**Problem:** `tasks/processing.py` creates a new event loop per task with `_run_async()`. This is fragile, wastes async benefits, and is the most likely source of production bugs.

**Option A (recommended): Make the pipeline synchronous.** The modules (validation, fix_generator, security_auditor, approval) use `async` primarily for the LLM and GitHub API calls. Celery tasks already run in worker processes. Convert the pipeline functions to synchronous, using `httpx.Client` (sync) instead of `httpx.AsyncClient` for API calls within Celery tasks.

**Option B: Use Celery's native async support.** Celery 5.x supports async tasks natively. Change the task decorators and remove `_run_async()`.

**Recommended approach:** Option A is simpler and avoids event-loop complexity in worker processes. The async API surface is small (GitHub API calls, LLM calls) and the sync equivalents are straightforward.

**Files affected:**
- `tasks/processing.py` — Remove `_run_async()`, call sync versions directly
- `modules/validation.py` — `parse_issue()` and `validate_issue()` become sync
- `modules/fix_generator.py` — `call_llm()` and `generate_fix()` become sync
- `modules/security_auditor.py` — `audit_fix()` becomes sync
- `modules/approval.py` — `post_proposal_comment()`, `poll_for_approval()`, `create_pull_request()` become sync
- `services/github_service.py` — Add sync methods alongside async (for Celery) or create a `SyncGitHubService`
- `services/llm_service.py` — Add sync `complete()` method using `openai.OpenAI` (sync client)

### 2.6 Unify Session Management

**Problem:** Three different patterns for database session management across the codebase.

**Fix:** Establish one pattern and use it everywhere:

```python
# In app/dependencies.py (already exists)
def get_db() -> Generator[Session, None, None]:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- **FastAPI routes:** Use `Depends(get_db)` — already set up in `app/dependencies.py`
- **Celery tasks:** Use a context manager version:
  ```python
  from contextlib import contextmanager

  @contextmanager
  def get_db_session():
      SessionLocal = get_session_factory()
      db = SessionLocal()
      try:
          yield db
          db.commit()
      except Exception:
          db.rollback()
          raise
      finally:
          db.close()
  ```
- **Remove** inline session management from `modules/monitoring.py:157-168`, `app/main.py:170-229`, and `modules/approval.py`.

---

## Phase 3: HARDEN CORE — Strengthen the Differentiators

**Objective:** Make the security audit pipeline and sandbox reproduction genuinely better than alternatives.

### 3.1 Deepen Security Audit Pipeline

This is AutoResolve's strongest differentiator. Make it count.

- **Expand CWE mapping** in `modules/security_auditor.py`. The current `CWE_SEVERITY_MAP` has 15 entries. Expand to cover the full OWASP Top 10 with at least 3 CWEs each.
- **Make PR security reports actionable.** Currently the approval comment shows a severity count table. Add: the specific CWE identifier, a one-line fix suggestion, and a link to the OWASP reference for each finding.
- **Add Semgrep rule coverage for Python-specific vulnerabilities:** pickle deserialization, subprocess injection, path traversal in file operations, SSTI (server-side template injection).

### 3.2 Improve Sandbox Reproduction

- **Better match scoring** in `_compute_similarity()` (`modules/validation.py:519-539`). The current implementation uses simple word overlap. Replace with:
  - Exact error type match: 1.0
  - Error type match + partial message match: 0.9
  - Exit code non-zero but no error type match: 0.4
  - Success (exit code 0): 0.0
- **Extract and validate reproduction scripts from issues.** The current extraction relies on the LLM parsing step. Add a fallback that looks for markdown code blocks with shell commands (````bash` or ````sh` blocks).
- **Timeout feedback.** When sandbox execution times out, report the timeout clearly in the validation result instead of returning a generic error.

### 3.3 Fix Diff Application

**Problem:** `_apply_diff_to_content` in `modules/approval.py` flattens directory structure by extracting only the basename.

**Fix:** Recreate the directory structure inside the temp directory before applying the patch:

```python
def _apply_diff_to_content(content: str, diff: str, file_path: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        # Recreate directory structure
        full_path = os.path.join(tmpdir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w") as f:
            f.write(content)

        # Apply patch
        result = subprocess.run(
            ["git", "apply", "--directory", tmpdir],
            input=diff.encode(),
            capture_output=True,
        )
        # ... read back and return
```

### 3.4 Use tiktoken for Token Estimation

**Problem:** `modules/fix_generator.py` uses `len(text) // 4` while `services/llm_service.py` has proper tiktoken support.

**Fix:** Have `build_fix_prompt()` call `LLMService.count_tokens()` instead of the local `estimate_tokens()` function. Or move the tiktoken logic to a shared utility.

---

## Phase 4: VALIDATE — End-to-End Proof

**Objective:** Prove the pipeline works against a real issue on a real repository.

### 4.1 Create an Integration Test Suite

- Set up a test repository with a known, reproducible Python bug (e.g., a `TypeError` from passing `None` to a function expecting a string)
- Write an integration test that:
  1. Posts a webhook payload simulating the issue
  2. Verifies the issue is queued and validated
  3. Verifies a fix is generated and passes syntax check
  4. Verifies the security audit completes
  5. Verifies the approval comment is well-formed

### 4.2 Run Against a Real GitHub Repository

- Fork a small Python repo with an open, reproducible bug
- Configure AutoResolve to monitor it
- Trigger the full pipeline
- Document what works, what breaks, and what the resulting PR looks like

---

## Phase Summary

| Phase | Effort | Impact | Dependency |
|-------|--------|--------|------------|
| **Phase 1: CUT** | Small (delete code) | Medium (reduced surface area, clearer scope) | None |
| **Phase 2: FIX** | Medium (infrastructure changes) | High (tests become trustworthy, engine perf fixed) | None |
| **Phase 3: HARDEN** | Medium (feature work) | High (differentiator becomes real) | Phase 2 |
| **Phase 4: VALIDATE** | Small (integration test) | Critical (proof of life) | Phase 2 + 3 |

**Execution order:** Phase 1 and Phase 2 can proceed in parallel. Phase 3 depends on Phase 2. Phase 4 depends on everything.

---

## What's NOT in This Plan

These are explicitly deferred:

- **GitHub App authentication** — Use `GITHUB_TOKEN` for now. Implement when deploying to multiple repos.
- **Dynamic security analysis** — Static analysis first. Fuzz testing in v2.
- **Multi-language support** — Ship Python-only. Add JavaScript/TypeScript first when there's demand.
- **Notifications** — Add Slack integration after the first successful end-to-end run.
- **Observability** — Add Sentry/Prometheus after production deployment.
- **Reaction-based approval** — Keep `@autoresolve approve/reject` commands only.
