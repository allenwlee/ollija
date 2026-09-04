---
date: 2026-09-04
topic: project-initialization
---

# Project Initialization

## What We're Building

Add an explicit, deterministic `ollija init` command that initializes the Git repository in
which it is run. Initialization creates a tracked `.ollija/project.yaml`, a profile-appropriate
guide template, the configured plan directory, and Ollija's neutral skill in the shared user skill
root without requiring users to copy files from an Ollija source checkout.

The default profile is `plan-only`: it supports shared Markdown plans without inventing staging,
production, deployment, or canonical release-worktree facts. Existing version-one contracts that
contain the full delivery configuration remain supported as the `delivery` profile.

## Why This Approach

Package installation is intentionally side-effect free because an installer has no reliable
consumer-project context. An explicit project initialization command gives both people and agents
one safe, repeatable bootstrap operation while keeping filesystem mutations visible and scoped.

## Key Decisions

- Initialization is explicit: package installation never writes into the current directory.
- `plan-only` is the default; `delivery` is opt-in and existing contracts remain compatible.
- `docs/plans` is a configurable default, not a hardcoded requirement.
- Initialization derives repository identity from local Git facts and accepts deterministic
  overrides where discovery is unavailable.
- Re-running initialization returns an unchanged result; conflicting existing files fail without
  partial writes or implicit overwrites.
- Plan-only contracts derive their repository root from `.ollija/project.yaml` instead of storing
  a machine-specific absolute checkout path.
- The Python package installation supplies the global `ollija` command; initialization verifies
  that setup and installs the packaged neutral agent skill unless explicitly disabled.
- Plan-only guidance never emits deployment, promotion, or worktree-relocation instructions.

## Open Questions

None.

## Next Steps

Implement, verify, merge privately, then install the CLI and neutral agent skill locally.
