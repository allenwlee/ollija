## Ollija Plan Guide

This block is generated guidance. Do not edit it directly. Correct durable facts in
`.ollija/project.yaml` or this template, then rerun `ollija annotate-plan`. Put an
owner-directed exception in the editable Delivery Exceptions section below.

### Resolved locations

- Profile: `${profile}`
- Authoritative host: `${canonical_host}`
- Authoritative repository: `${repository_root}`
- Active worktree: `${active_worktree}`
- Plan: `${plan_path}`
- Change: `${change_id}`
- Branch: `${branch}`

### Planning scope

- Workflow: `${workflow}`
- Delivery target: `${delivery_target}`
- Owner selection recorded: `${delivery_selected_by_user}`

${verification}

### Boundaries

- No staging or production delivery authority is defined by the plan-only profile.
- Creating or updating this plan does not authorize commits, pushes, deployment, or cleanup.
- The ${code_failure_route} owns implementation, verification, and every mutation.
- Ollija does not start a persistent process or retain project runtime state.
