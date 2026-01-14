#!/usr/bin/env python3
"""
GitHub App setup helper for AutoResolve.

Guides users through creating and configuring a GitHub App for AutoResolve.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional


def print_step(step: int, message: str):
    """Print a numbered step."""
    print(f"\n{'='*60}")
    print(f"Step {step}: {message}")
    print("=" * 60)


def print_info(message: str):
    """Print an info message."""
    print(f"  → {message}")


def get_input(prompt: str, default: Optional[str] = None) -> str:
    """Get user input with optional default."""
    if default:
        result = input(f"  {prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"  {prompt}: ").strip()


def generate_manifest(app_name: str, webhook_url: str, homepage_url: str) -> dict:
    """Generate GitHub App manifest for creation."""
    return {
        "name": app_name,
        "url": homepage_url,
        "hook_attributes": {"url": webhook_url, "active": True},
        "redirect_url": f"{homepage_url}/github/callback",
        "callback_urls": [f"{homepage_url}/github/callback"],
        "public": False,
        "default_permissions": {
            "issues": "write",
            "pull_requests": "write",
            "contents": "write",
            "metadata": "read",
            "statuses": "write",
            "checks": "write",
        },
        "default_events": [
            "issues",
            "issue_comment",
            "pull_request",
            "pull_request_review",
            "pull_request_review_comment",
        ],
    }


def setup_interactive():
    """Run interactive setup wizard."""
    print("\n" + "=" * 60)
    print("  AutoResolve GitHub App Setup Wizard")
    print("=" * 60)
    print("\nThis wizard will help you set up a GitHub App for AutoResolve.")
    print("You'll need admin access to your GitHub organization or account.\n")

    # Step 1: Gather information
    print_step(1, "Gather App Information")

    app_name = get_input("App name", "AutoResolve")
    webhook_url = get_input("Webhook URL (e.g., https://your-domain.com/api/webhook)")
    homepage_url = get_input(
        "Homepage URL",
        (
            webhook_url.rsplit("/api", 1)[0]
            if "/api" in webhook_url
            else "https://github.com/your-org/autoresolve"
        ),
    )

    # Step 2: Generate manifest
    print_step(2, "Generate App Manifest")

    manifest = generate_manifest(app_name, webhook_url, homepage_url)
    manifest_json = json.dumps(manifest, indent=2)

    print_info("Generated manifest:")
    print(manifest_json)

    # Save manifest
    manifest_path = Path("github_app_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest_json)
    print_info(f"Saved to {manifest_path}")

    # Step 3: Create the app
    print_step(3, "Create the GitHub App")

    print_info("Option A: Create via manifest (recommended)")
    print("  1. Go to: https://github.com/settings/apps/new")
    print("  2. Or for org: https://github.com/organizations/{org}/settings/apps/new")
    print(f"  3. Upload the manifest file: {manifest_path.absolute()}")
    print()
    print_info("Option B: Create manually")
    print("  1. Go to GitHub Settings → Developer settings → GitHub Apps")
    print("  2. Click 'New GitHub App'")
    print("  3. Fill in the following:")
    print(f"     - App name: {app_name}")
    print(f"     - Homepage URL: {homepage_url}")
    print(f"     - Webhook URL: {webhook_url}")
    print("     - Webhook secret: (generate a secure random string)")
    print("  4. Set permissions:")
    print("     - Issues: Read & Write")
    print("     - Pull requests: Read & Write")
    print("     - Contents: Read & Write")
    print("     - Metadata: Read-only")
    print("     - Commit statuses: Read & Write")
    print("     - Checks: Read & Write")
    print("  5. Subscribe to events:")
    print("     - Issues, Issue comment")
    print("     - Pull request, Pull request review, Pull request review comment")

    input("\n  Press Enter when you've created the app...")

    # Step 4: Get credentials
    print_step(4, "Configure Credentials")

    app_id = get_input("GitHub App ID")

    print_info("Now you need to generate a private key:")
    print("  1. Go to your app's settings page")
    print("  2. Scroll to 'Private keys' and click 'Generate a private key'")
    print("  3. Save the downloaded .pem file")

    private_key_path = get_input("Path to private key file", "private-key.pem")
    webhook_secret = get_input("Webhook secret")

    # Step 5: Generate config
    print_step(5, "Generate Configuration")

    # Create secrets directory
    secrets_dir = Path("secrets")
    secrets_dir.mkdir(exist_ok=True)

    # Save app ID
    (secrets_dir / "github_app_id").write_text(app_id)
    print_info(f"Saved app ID to {secrets_dir}/github_app_id")

    # Save webhook secret
    (secrets_dir / "github_webhook_secret").write_text(webhook_secret)
    print_info(f"Saved webhook secret to {secrets_dir}/github_webhook_secret")

    # Check if private key exists
    if Path(private_key_path).exists():
        import shutil

        shutil.copy(private_key_path, secrets_dir / "github_private_key.pem")
        print_info(f"Copied private key to {secrets_dir}/github_private_key.pem")
    else:
        print_info(f"Copy your private key to {secrets_dir}/github_private_key.pem")

    # Generate .env file
    print_step(6, "Generate Environment File")

    env_content = f"""# AutoResolve Environment Configuration
# Generated by setup_github_app.py

# GitHub App
GITHUB_APP_ID={app_id}
GITHUB_WEBHOOK_SECRET={webhook_secret}
GITHUB_PRIVATE_KEY_PATH=secrets/github_private_key.pem

# Database
DATABASE_URL=postgresql://autoresolve:password@localhost:5432/autoresolve

# Redis
REDIS_URL=redis://localhost:6379/0

# Celery
CELERY_BROKER_URL=amqp://guest:guest@localhost:5672//

# LLM (add your API key)
OPENAI_API_KEY=your-openai-api-key-here
"""

    env_path = Path(".env")
    if env_path.exists():
        overwrite = get_input(".env already exists. Overwrite? (y/N)", "n")
        if overwrite.lower() != "y":
            env_path = Path(".env.new")

    env_path.write_text(env_content)
    print_info(f"Saved environment config to {env_path}")

    # Step 7: Install the app
    print_step(7, "Install the App")

    print_info("Install the app on your repositories:")
    print("  1. Go to your app's settings page")
    print("  2. Click 'Install App' in the sidebar")
    print("  3. Select your organization or account")
    print("  4. Choose which repositories to enable")
    print()
    print_info("Or install via URL:")
    print(
        f"  https://github.com/apps/{app_name.lower().replace(' ', '-')}/installations/new"
    )

    # Done
    print("\n" + "=" * 60)
    print("  Setup Complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Add your OpenAI API key to .env")
    print("  2. Start the services: docker-compose up -d")
    print("  3. Test the webhook: curl -X POST http://localhost:8000/api/health")
    print()


def _is_placeholder_value(env_content: str, var: str) -> bool:
    """Check if an environment variable has a placeholder value."""
    if f"{var}=your-" in env_content:
        return True
    if f"{var}=" not in env_content:
        return False
    value = env_content.split(f"{var}=")[1].split("\n")[0].strip()
    return value == ""


def _validate_env_file() -> tuple[list[str], list[str]]:
    """Validate .env file contents."""
    errors = []
    warnings = []
    env_path = Path(".env")

    if not env_path.exists():
        errors.append(".env file not found")
        return errors, warnings

    env_content = env_path.read_text(encoding="utf-8")
    required_vars = ["GITHUB_APP_ID", "GITHUB_WEBHOOK_SECRET", "DATABASE_URL", "OPENAI_API_KEY"]

    for var in required_vars:
        if var not in env_content:
            errors.append(f"Missing {var} in .env")
        elif _is_placeholder_value(env_content, var):
            warnings.append(f"{var} appears to be a placeholder")

    return errors, warnings


def _validate_secrets_dir() -> tuple[list[str], list[str]]:
    """Validate secrets directory contents."""
    errors = []
    warnings = []
    secrets_dir = Path("secrets")

    if not secrets_dir.exists():
        warnings.append("secrets/ directory not found")
    elif not (secrets_dir / "github_private_key.pem").exists():
        errors.append("GitHub private key not found in secrets/")

    return errors, warnings


def _print_validation_report(errors: list[str], warnings: list[str]) -> bool:
    """Print validation results and return success status."""
    if errors:
        print("ERRORS:")
        for error in errors:
            print(f"  ✗ {error}")

    if warnings:
        print("\nWARNINGS:")
        for warning in warnings:
            print(f"  ⚠ {warning}")

    if not errors and not warnings:
        print("✓ All configuration looks good!")

    return len(errors) == 0


def validate_config():
    """Validate existing configuration."""
    print("\nValidating AutoResolve configuration...\n")

    # Collect all errors and warnings
    env_errors, env_warnings = _validate_env_file()
    secrets_errors, secrets_warnings = _validate_secrets_dir()

    errors = env_errors + secrets_errors
    warnings = env_warnings + secrets_warnings

    # Check config.yaml
    if not Path("config.yaml").exists():
        warnings.append("config.yaml not found (will use defaults)")

    return _print_validation_report(errors, warnings)


def main():
    """Entry point for the GitHub App setup helper CLI."""
    parser = argparse.ArgumentParser(description="AutoResolve GitHub App setup helper")
    parser.add_argument(
        "--validate", action="store_true", help="Validate existing configuration"
    )
    parser.add_argument(
        "--manifest-only", action="store_true", help="Only generate the manifest file"
    )

    args = parser.parse_args()

    if args.validate:
        sys.exit(0 if validate_config() else 1)
    elif args.manifest_only:
        app_name = os.getenv("APP_NAME", "AutoResolve")
        webhook_url = os.getenv("WEBHOOK_URL", "https://your-domain.com/api/webhook")
        homepage_url = os.getenv(
            "HOMEPAGE_URL", "https://github.com/your-org/autoresolve"
        )

        manifest = generate_manifest(app_name, webhook_url, homepage_url)
        print(json.dumps(manifest, indent=2))
    else:
        setup_interactive()


if __name__ == "__main__":
    main()
