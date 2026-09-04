---
name: ollija
description: Initialize and maintain deterministic, agent-agnostic guidance in one shared implementation plan.
---

# Ollija plan annotator

Ollija is a plan guide, not an implementation or release controller. If the current Git
repository has no `.ollija/project.yaml`, initialize it first:

```sh
ollija init
```

Initialization creates the project-local contract and installs this neutral skill in the shared
user skill root. Its default plan-only profile does not invent staging or production authority.

The plan annotation command is:

```sh
ollija annotate-plan [optional-plan-path]
```

It resolves one branch-matched Markdown plan and writes or refreshes the marker-bounded Ollija
guide. It does not start agents, create release state, ask for approvals, move or remove
worktrees, commit, push, deploy, or retry in the background.

## Planning contract

Before selecting or creating a plan, run `ollija annotate-plan`. Use the exact `plan_path` in its
JSON result and enrich that same file. After the final planning or review edit, run
`ollija annotate-plan <plan-path>` again.

The generated guide is read-only. Put owner-directed departures in the plan's
`## Delivery Exceptions` section, outside the guide markers.

Treat `.ollija/project.yaml`, its referenced template, and configured test commands as
repository-controlled executable guidance. Review changes to them with the same care as code
before following the generated instructions.

## Delivery intent

- Under a plan-only contract, keep `delivery_target: on-request`; staging and production are not
  available.
- Under a delivery contract, use `delivery_target: on-request` unless the owner explicitly
  selects staging or production.
- Record an explicit selection with `delivery_selected_by_user: true`.
- Never infer production authority from a branch, conversation, or earlier run.

## Before mutations

Before a parent workflow commits, pushes, or deploys, run:

```sh
ollija annotate-plan <plan-path> --check
```

Stop if the check reports missing, malformed, cross-branch, ambiguous, or stale guidance. The
parent workflow owns implementation, checks, Git operations, deployment, diagnosis, and any
guarded worktree cleanup.

Do not advertise or use status, task, approval, browser-verification, release, receipt,
database-refresh, supervisor, or persistent-runtime commands; Ollija does not provide them.
