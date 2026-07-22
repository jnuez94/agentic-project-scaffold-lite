# Security Policy

This framework is documentation-first, but it is intended for projects that may involve sensitive work.

## Reporting Security Issues

Report vulnerabilities privately through [GitHub Security Advisories](https://github.com/jnuez94/agentic-project-scaffold-lite/security/advisories/new).

The maintainer will acknowledge a report within seven days and will coordinate validation, remediation, and disclosure with the reporter. Do not open a public issue until a disclosure is published or the maintainer confirms that public discussion is safe.

Do not report secrets, credentials, private customer data, regulated data, or exploit details in public issues.

## Sensitive Data Guidance

Coordination records should not contain:

- passwords
- API keys
- private keys
- session tokens
- real customer data
- regulated health, financial, legal, or personal data
- proprietary material that has not been approved for the project record

Use references to approved storage locations instead of copying sensitive content into task, message, or review records.

## Security Review Expectations

Any implementation or adapter that stores coordination records should define:

- authentication expectations
- authorization model
- audit history
- data retention
- backup and recovery
- redaction process
- incident response owner
- external sharing rules

## Scope

This file does not certify any implementation as secure. It defines the minimum security posture expected from projects adopting the working model.
