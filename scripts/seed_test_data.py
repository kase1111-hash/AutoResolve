#!/usr/bin/env python3
"""
Seed test data for AutoResolve development.

Creates sample issues, proposals, and approvals for testing.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import uuid4

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_sample_issues():
    """Get sample issue data."""
    return [
        {
            "github_issue_id": 1,
            "repo_full_name": "test-org/test-repo",
            "title": "NullPointerException in OrderService.processOrder",
            "body": """## Bug Report

**Description:**
The application crashes with a NullPointerException when calling `processOrder` with a null order.

**Stack Trace:**
```
java.lang.NullPointerException
    at com.example.OrderService.processOrder(OrderService.java:42)
    at com.example.OrderController.submitOrder(OrderController.java:28)
```

**Expected Behavior:**
Should validate input and throw IllegalArgumentException for null orders.

**Environment:**
- Java 17
- Spring Boot 3.0
""",
            "labels": ["bug", "autoresolve"],
            "error_type": "NullPointerException",
            "error_signature": "NPE:OrderService.processOrder:42"
        },
        {
            "github_issue_id": 2,
            "repo_full_name": "test-org/test-repo",
            "title": "TypeError: Cannot read property 'map' of undefined",
            "body": """## Bug Report

**Description:**
UserList component crashes when users prop is undefined.

**Error:**
```
TypeError: Cannot read property 'map' of undefined
    at UserList (UserList.js:12)
    at renderWithHooks (react-dom.development.js:14985)
```

**Steps to Reproduce:**
1. Render UserList without users prop
2. Component crashes

**Expected:**
Should handle undefined users gracefully.
""",
            "labels": ["bug", "frontend", "autoresolve"],
            "error_type": "TypeError",
            "error_signature": "TypeError:UserList:map:undefined"
        },
        {
            "github_issue_id": 3,
            "repo_full_name": "test-org/python-app",
            "title": "AttributeError in authentication module",
            "body": """## Bug

`authenticate()` passes None to `get_user()` instead of the username.

```python
File "auth/login.py", line 40, in authenticate
    user = get_user(None)
AttributeError: 'NoneType' object has no attribute 'password_hash'
```

Should pass the username parameter.
""",
            "labels": ["bug", "autoresolve", "security"],
            "error_type": "AttributeError",
            "error_signature": "AttributeError:authenticate:get_user:None"
        },
        {
            "github_issue_id": 4,
            "repo_full_name": "test-org/python-app",
            "title": "SQL Injection vulnerability in user lookup",
            "body": """## Security Issue

**Severity:** High

The `get_user_by_email` function in `db/queries.py` is vulnerable to SQL injection.

**Vulnerable Code:**
```python
query = f"SELECT * FROM users WHERE email = '{email}'"
```

**Fix:**
Use parameterized queries instead.
""",
            "labels": ["security", "autoresolve", "high-priority"],
            "error_type": "SQL_INJECTION",
            "error_signature": "SQLI:get_user_by_email:queries.py"
        }
    ]


def get_sample_proposals():
    """Get sample fix proposals."""
    return [
        {
            "issue_index": 0,
            "suggested_patch": """--- a/src/main/java/com/example/OrderService.java
+++ b/src/main/java/com/example/OrderService.java
@@ -40,6 +40,9 @@ public class OrderService {
     }

     public void processOrder(Order order) {
+        if (order == null) {
+            throw new IllegalArgumentException("Order cannot be null");
+        }
         order.validate();
         orderRepository.save(order);
     }
""",
            "affected_files": ["src/main/java/com/example/OrderService.java"],
            "confidence_score": 0.95,
            "status": "pending_approval"
        },
        {
            "issue_index": 1,
            "suggested_patch": """--- a/src/components/UserList.js
+++ b/src/components/UserList.js
@@ -10,7 +10,11 @@ function UserList({ users }) {
   return (
     <div className="user-list">
-      {users.map(user => (
+      {users && users.map(user => (
         <UserCard key={user.id} user={user} />
       ))}
+      {!users && (
+        <p>No users found</p>
+      )}
     </div>
   );
 }
""",
            "affected_files": ["src/components/UserList.js"],
            "confidence_score": 0.92,
            "status": "approved"
        },
        {
            "issue_index": 3,
            "suggested_patch": """--- a/db/queries.py
+++ b/db/queries.py
@@ -15,7 +15,7 @@ def get_user_by_email(email: str):
     \"\"\"
     Retrieve user by email address.
     \"\"\"
-    query = f"SELECT * FROM users WHERE email = '{email}'"
-    return db.execute(query).fetchone()
+    query = "SELECT * FROM users WHERE email = ?"
+    return db.execute(query, (email,)).fetchone()
""",
            "affected_files": ["db/queries.py"],
            "confidence_score": 0.98,
            "status": "merged"
        }
    ]


def seed_database(db_url: Optional[str] = None):
    """Seed the database with test data."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from models.database import Approval, Base, FixProposal, Issue, MonitoredRepo
    except ImportError as e:
        print(f"Error importing models: {e}")
        print("Make sure you're running from the project root with dependencies installed.")
        return False

    # Get database URL
    if not db_url:
        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql://autoresolve:password@localhost:5432/autoresolve"
        )

    print(f"Connecting to database: {db_url.split('@')[1] if '@' in db_url else db_url}")

    try:
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return False

    # Seed monitored repos
    print("\nSeeding monitored repositories...")
    repos = ["test-org/test-repo", "test-org/python-app"]
    for repo_name in repos:
        existing = db.query(MonitoredRepo).filter(
            MonitoredRepo.repo_full_name == repo_name
        ).first()
        if not existing:
            repo = MonitoredRepo(
                repo_full_name=repo_name,
                installation_id=12345,
                enabled=True,
                created_at=datetime.utcnow()
            )
            db.add(repo)
            print(f"  + {repo_name}")
        else:
            print(f"  - {repo_name} (exists)")

    # Seed issues
    print("\nSeeding issues...")
    sample_issues = get_sample_issues()
    db_issues = []

    for issue_data in sample_issues:
        existing = db.query(Issue).filter(
            Issue.github_issue_id == issue_data["github_issue_id"],
            Issue.repo_full_name == issue_data["repo_full_name"]
        ).first()

        if not existing:
            issue = Issue(
                queue_id=str(uuid4()),
                github_issue_id=issue_data["github_issue_id"],
                repo_full_name=issue_data["repo_full_name"],
                title=issue_data["title"],
                body=issue_data["body"],
                labels=issue_data["labels"],
                error_type=issue_data.get("error_type"),
                error_signature=issue_data.get("error_signature"),
                status="new",
                created_at=datetime.utcnow() - timedelta(hours=len(db_issues) * 2),
                updated_at=datetime.utcnow()
            )
            db.add(issue)
            db.flush()
            db_issues.append(issue)
            print(f"  + Issue #{issue_data['github_issue_id']}: {issue_data['title'][:50]}...")
        else:
            db_issues.append(existing)
            print(f"  - Issue #{issue_data['github_issue_id']} (exists)")

    # Seed proposals
    print("\nSeeding fix proposals...")
    sample_proposals = get_sample_proposals()

    for prop_data in sample_proposals:
        issue = db_issues[prop_data["issue_index"]]

        existing = db.query(FixProposal).filter(
            FixProposal.issue_id == issue.id
        ).first()

        if not existing:
            proposal = FixProposal(
                proposal_id=str(uuid4()),
                issue_id=issue.id,
                suggested_patch=prop_data["suggested_patch"],
                affected_files=prop_data["affected_files"],
                confidence_score=prop_data["confidence_score"],
                status=prop_data["status"],
                generated_at=datetime.utcnow() - timedelta(hours=prop_data["issue_index"]),
                model_used="gpt-4",
                prompt_tokens=500,
                completion_tokens=200
            )
            db.add(proposal)
            db.flush()

            # Update issue status
            if prop_data["status"] == "pending_approval":
                issue.status = "pending_approval"
            elif prop_data["status"] in ("approved", "merged"):
                issue.status = prop_data["status"]

            # Create approval record
            if prop_data["status"] in ("approved", "merged"):
                approval = Approval(
                    proposal_id=proposal.id,
                    status="approved",
                    approved_by="test-maintainer",
                    approved_at=datetime.utcnow() - timedelta(minutes=30),
                    resolved_at=datetime.utcnow() - timedelta(minutes=30)
                )
                db.add(approval)

            print(f"  + Proposal for issue #{issue.github_issue_id} ({prop_data['status']})")
        else:
            print(f"  - Proposal for issue #{issue.github_issue_id} (exists)")

    db.commit()
    db.close()

    print("\n✓ Database seeded successfully!")
    return True


def seed_fixtures():
    """Seed JSON fixture files for testing."""
    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # Sample issues JSON
    issues_path = fixtures_dir / "sample_issues.json"
    if not issues_path.exists():
        issues = get_sample_issues()
        issues_path.write_text(json.dumps(issues, indent=2))
        print(f"Created {issues_path}")

    # Sample proposals
    proposals_path = fixtures_dir / "sample_proposals.json"
    proposals = get_sample_proposals()
    proposals_path.write_text(json.dumps(proposals, indent=2))
    print(f"Created {proposals_path}")

    print("\n✓ Fixtures created successfully!")


def clear_database(db_url: Optional[str] = None):
    """Clear all test data from database."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from models.database import (
            Approval,
            AuditLog,
            FixProposal,
            Issue,
            SecurityReport,
            Validation,
        )
    except ImportError as e:
        print(f"Error importing models: {e}")
        return False

    if not db_url:
        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql://autoresolve:password@localhost:5432/autoresolve"
        )

    confirm = input(f"Clear all data from {db_url.split('@')[1]}? (y/N): ")
    if confirm.lower() != "y":
        print("Aborted.")
        return False

    try:
        engine = create_engine(db_url)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        # Delete in order due to foreign keys
        db.query(AuditLog).delete()
        db.query(Approval).delete()
        db.query(SecurityReport).delete()
        db.query(FixProposal).delete()
        db.query(Validation).delete()
        db.query(Issue).delete()

        db.commit()
        db.close()

        print("✓ Database cleared!")
        return True

    except Exception as e:
        print(f"Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Seed test data for AutoResolve development"
    )
    parser.add_argument(
        "--database-url",
        help="Database URL (default: from DATABASE_URL env var)"
    )
    parser.add_argument(
        "--fixtures-only",
        action="store_true",
        help="Only create fixture files, don't touch database"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing test data instead of seeding"
    )

    args = parser.parse_args()

    if args.clear:
        sys.exit(0 if clear_database(args.database_url) else 1)
    elif args.fixtures_only:
        seed_fixtures()
    else:
        seed_fixtures()
        seed_database(args.database_url)


if __name__ == "__main__":
    main()
