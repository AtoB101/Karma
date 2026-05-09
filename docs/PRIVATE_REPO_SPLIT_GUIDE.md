# Private Repository Split Guide

This public repository only keeps open components.

## Removed sensitive categories

- Internal investor and fundraising narrative docs
- Internal tokenomics parameter docs
- Private integration/operation runbooks
- Private community governance operation templates
- Advanced private integration scripts and examples

## Recommended private repository structure

Create a private repository (for example: `karma-internal`) and move internal files there:

- `docs/private/**` for internal strategy, tokenomics, investor materials
- `scripts/private/**` for private operations and partner integrations
- `examples/private/**` for private scenario demos
- `outreach/**` for commercial leads and campaign records

## Secure sharing policy

- Never commit real private keys or mnemonic phrases
- Keep partner credentials and API secrets only in private secret managers
- Use least-privilege accounts for CI tokens and RPC keys
- Rotate test credentials regularly

## Public repo policy

Public repository should contain only:

- auditable contract code
- public examples and onboarding docs
- open-source safe scripts (no private customer data, no internal strategy)

