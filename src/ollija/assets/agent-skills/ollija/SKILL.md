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

The generated guide is read-only. Current explicit owner instructions govern this task.
Record departures in `## Delivery Exceptions` and reflect the selected route in metadata;
do not recreate a removed requirement in another checklist.

To remove Ollija from one plan, retain only its branch identity and opt-out:

```yaml
ollija:
  enabled: false
  branch: feat/example
```

Annotation, check mode, and branch discovery leave that plan byte-identical and create no
replacement. Remove the old guide when opting out; disabled annotation does not edit it.
Re-enable only on explicit owner direction, restoring valid managed metadata.

Treat `.ollija/project.yaml`, its referenced template, and configured test commands as
repository-controlled executable guidance. Review changes to them with the same care as code
before following the generated instructions.

## Delivery intent

- Under a plan-only contract, keep `delivery_target: on-request`; staging and production are not
  available.
- Under a delivery contract, use `delivery_target: on-request` unless the owner explicitly
  selects staging or production.
- Record an explicit selection with `delivery_selected_by_user: true`.
- Preserve explicit owner authorization from the current task, including an authorized continuation. A branch name or historical release alone grants no authority. A status question does not cancel an active delivery.

## Delivery routes

Existing delivery plans default to `delivery_route: staged` and `staging_transport: branch`.
Production selection alone does not waive staging. For an explicit owner-selected direct route:

```sh
ollija annotate-plan <plan-path> --delivery-target production --delivery-selected-by-user --delivery-route direct --delivery-route-selected-by-user
```

For exact-commit staging, select `--delivery-route staged --delivery-route-selected-by-user
--staging-transport commit`. This avoids moving the shared staging branch; the parent still
checks service/database occupancy and verifies the deployed revision. Ollija executes neither
route. Preserve the selected route when resuming or reannotating; opt-out takes precedence.

## Before mutations

Before a parent workflow commits, pushes, or deploys, run:

```sh
ollija annotate-plan <plan-path> --check
```

Repair missing, malformed, cross-branch, ambiguous, or stale managed guidance before following it. Disabled plans need no generated guide. A guide never reinstates an explicitly removed requirement. The
parent workflow owns implementation, checks, Git operations, deployment, diagnosis, and any
guarded worktree cleanup.

Do not advertise or use status, task, approval, browser-verification, release, receipt,
database-refresh, supervisor, or persistent-runtime commands; Ollija does not provide them.
