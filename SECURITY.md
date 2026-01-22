# Security Policy

## Supported Versions

We release patches for security vulnerabilities for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take the security of AutoResolve seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via one of the following methods:

1. **GitHub Security Advisories**: Use [GitHub's private vulnerability reporting](https://github.com/kase1111-hash/AutoResolve/security/advisories/new) feature.

2. **Email**: Send an email to the maintainers with details of the vulnerability.

### What to Include

When reporting a vulnerability, please include:

1. **Description**: A clear description of the vulnerability
2. **Impact**: The potential impact of the vulnerability
3. **Reproduction Steps**: Detailed steps to reproduce the issue
4. **Affected Versions**: Which versions are affected
5. **Suggested Fix**: If you have a suggested fix, please include it

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your report within 48 hours
- **Initial Assessment**: We will provide an initial assessment within 7 days
- **Regular Updates**: We will keep you informed of our progress
- **Resolution**: We aim to resolve critical vulnerabilities within 30 days
- **Credit**: We will credit you in the security advisory (unless you prefer to remain anonymous)

### Disclosure Policy

- We follow a coordinated disclosure process
- We will work with you to understand and resolve the issue
- We will not take legal action against researchers who follow this policy
- We will publicly acknowledge your contribution (with your permission)

## Security Measures

AutoResolve implements several security measures:

### Authentication & Authorization

- **Webhook Signature Verification**: All GitHub webhooks are verified using HMAC-SHA256 signatures
- **API Key Authentication**: Management API endpoints require API key authentication
- **Maintainer Verification**: Only repository maintainers can approve fix proposals

### Sandbox Isolation

- **Network Isolation**: Sandbox containers run with `network_mode: none`
- **Resource Limits**: Memory (512MB) and CPU quotas prevent resource exhaustion
- **Timeout Enforcement**: 5-minute maximum execution time
- **Read-only Mounts**: Source code is mounted read-only where possible

### Code Security

- **Static Analysis**: All generated patches are scanned with Bandit and Semgrep
- **OWASP Coverage**: Security scans include OWASP Top 10 vulnerability detection
- **Automatic Rejection**: Patches with critical vulnerabilities are automatically rejected
- **Dynamic Analysis**: Optional fuzz testing for runtime vulnerability detection

### Data Protection

- **Secret Management**: Secrets are stored as environment variables, never in code
- **Audit Logging**: All actions are logged with full audit trails
- **Database Security**: Parameterized queries prevent SQL injection

### Infrastructure Security

- **HTTPS Only**: All external communications use TLS
- **Rate Limiting**: API endpoints are rate-limited to prevent abuse
- **Deduplication**: Redis-based deduplication prevents replay attacks

## Security Best Practices for Deployment

When deploying AutoResolve, follow these best practices:

### Environment Variables

```bash
# Use strong, unique secrets
APP_SECRET_KEY=<generate-256-bit-random-key>
GITHUB_WEBHOOK_SECRET=<generate-unique-webhook-secret>
API_KEY=<generate-unique-api-key>

# Never commit secrets to version control
# Use secret management solutions (AWS Secrets Manager, HashiCorp Vault, etc.)
```

### Network Configuration

- Deploy behind a reverse proxy (nginx, AWS ALB)
- Enable TLS termination at the load balancer
- Restrict database access to application servers only
- Use private subnets for internal services

### Container Security

- Run containers as non-root users
- Use minimal base images (slim/alpine variants)
- Regularly update base images for security patches
- Scan container images for vulnerabilities

### Monitoring

- Enable Sentry for error tracking
- Monitor for unusual patterns (high error rates, auth failures)
- Set up alerts for security-relevant events
- Review audit logs regularly

## Known Security Considerations

### LLM-Generated Code

AutoResolve uses LLMs to generate code patches. While we scan all generated code for vulnerabilities, be aware that:

- LLMs may occasionally generate insecure code patterns
- Security scans may have false negatives
- Human review is always recommended before merging
- Critical systems should require manual approval

### Docker Socket Access

The worker container requires Docker socket access to create sandbox containers. This is a privileged operation. Mitigations include:

- Running workers on dedicated hosts
- Using Docker-in-Docker or rootless Docker where possible
- Monitoring container creation/destruction

## Security Updates

Security updates are released as patch versions (e.g., 1.0.1). We recommend:

- Subscribing to GitHub releases for notifications
- Enabling Dependabot for dependency updates
- Regularly updating to the latest patch version

## Contact

For security-related questions that are not vulnerability reports, please open a GitHub Discussion or contact the maintainers.
