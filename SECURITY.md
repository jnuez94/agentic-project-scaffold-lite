# Security Policy

This framework is documentation-first, but it is intended for projects that may involve sensitive work.

## Reporting Security Issues

If this becomes a public open-source project, replace this section with the preferred reporting channel.

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
