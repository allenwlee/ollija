## Ollija Delivery Guide

This block is generated guidance. Do not edit it directly. Correct durable facts in `.ollija/project.yaml` or this template, then rerun `ollija annotate-plan`. Put an owner-directed exception in the editable Delivery Exceptions section below.

### Resolved locations

- Authoritative host: `${canonical_host}`
- Authoritative repository: `${repository_root}`
- ${release_worktree_label}: `${release_worktree_area}`
- Active worktree: `${active_worktree}`
- Plan: `${plan_path}`
- Change: `${change_id}`
- Branch: `${branch}`
- Staging branch and blueprint: `${staging_branch}`, `${staging_blueprint}`
- Production branch and blueprint: `${production_branch}`, `${production_blueprint}`
- Staging URL: `${staging_url}`
- Production URL: `${production_url}`

### Placement

${placement}

### Delivery scope

- Workflow: `${workflow}`
- Delivery target: `${delivery_target}`
- Owner selection recorded: `${delivery_selected_by_user}`

${delivery_actions}

### Failure handling

- Never promote a staging candidate whose automated checks failed.
- Implementation failures return to the ${code_failure_route} for diagnosis, correction, recommit, and restaging.
- Infrastructure failures use the ${infra_failure_route} first.
- Ollija's generated guidance is advisory; the parent workflow owns every mutation.
- Never force-remove a worktree. Retain staging-only, failed, dirty, locked, noncanonical, or candidate-mismatched worktrees for diagnosis or later delivery.
- Do not run an endless retry loop or start a persistent Ollija process.
