"""Pure, byte-preserving annotation for one Markdown plan."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from shlex import quote
from string import Template
from typing import Any

import yaml

from .config import ProjectConfig
from .worktrees import canonical_worktree_path, is_canonical_worktree

BEGIN_MARKER = "<!-- BEGIN OLLIJA DELIVERY GUIDE -->"
END_MARKER = "<!-- END OLLIJA DELIVERY GUIDE -->"
DELIVERY_EXCEPTIONS_HEADING = "## Delivery Exceptions"


class AnnotationError(ValueError):
    """A plan cannot be safely annotated without changing its human content."""


@dataclass(frozen=True, slots=True)
class PlanMetadata:
    change_id: str
    branch: str
    workflow: str
    delivery_target: str
    delivery_selected_by_user: bool


def _line(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise AnnotationError(f"ollija.{field} must be a non-empty line")
    return value.strip()


def _branch(value: Any) -> str:
    branch = _line(value, field="branch")
    path = Path(branch)
    if branch.startswith("/") or ".." in path.parts or branch.endswith("/") or "//" in branch:
        raise AnnotationError("ollija.branch must be a branch name")
    return branch


def _frontmatter_span(content: str) -> tuple[int, int]:
    if not content.startswith("---"):
        raise AnnotationError("plan must start with YAML frontmatter")
    first_newline = content.find("\n")
    if first_newline == -1 or content[:first_newline].rstrip("\r") != "---":
        raise AnnotationError("plan must start with YAML frontmatter")
    offset = first_newline + 1
    for line in content[offset:].splitlines(keepends=True):
        if line.rstrip("\r\n") in {"---", "..."}:
            return offset, offset + len(line)
        offset += len(line)
    raise AnnotationError("plan YAML frontmatter has no closing delimiter")


def parse_plan_metadata(content: str) -> PlanMetadata:
    """Read durable authority without serializing or otherwise changing the plan."""

    body_start, _ = _frontmatter_span(content)
    try:
        loaded = yaml.safe_load(content[4:body_start])
    except yaml.YAMLError as exc:
        raise AnnotationError(f"plan frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise AnnotationError("plan frontmatter must be a YAML mapping")
    raw = loaded.get("ollija")
    if not isinstance(raw, Mapping):
        raise AnnotationError("plan frontmatter must contain an ollija mapping")
    target = _line(raw.get("delivery_target"), field="delivery_target")
    if target not in {"on-request", "staging", "production"}:
        raise AnnotationError("ollija.delivery_target must be on-request, staging, or production")
    selected = raw.get("delivery_selected_by_user")
    if not isinstance(selected, bool):
        raise AnnotationError("ollija.delivery_selected_by_user must be a boolean")
    return PlanMetadata(
        change_id=_line(raw.get("change_id"), field="change_id"),
        branch=_branch(raw.get("branch")),
        workflow=_line(raw.get("workflow"), field="workflow"),
        delivery_target=target,
        delivery_selected_by_user=selected,
    )


def _marker_span(content: str) -> tuple[int, int] | None:
    begin = content.find(BEGIN_MARKER)
    end = content.find(END_MARKER)
    if begin == -1 and end == -1:
        return None
    if (
        begin == -1
        or end == -1
        or content.find(BEGIN_MARKER, begin + len(BEGIN_MARKER)) != -1
        or content.find(END_MARKER, end + len(END_MARKER)) != -1
        or begin > end
    ):
        raise AnnotationError("delivery guide marker structure is malformed")
    return begin, end + len(END_MARKER)


def _has_delivery_exceptions(content: str) -> bool:
    return any(line.rstrip("\r\n") == DELIVERY_EXCEPTIONS_HEADING for line in content.splitlines())


def _placement(config: ProjectConfig, metadata: PlanMetadata, active_worktree: Path) -> str:
    if is_canonical_worktree(config, active_worktree, metadata.branch):
        return (
            f"This worktree is inside the {config.authority.release_worktree_label}. "
            "Reuse it for the whole change. Do not create a second worktree or plan for this branch."
        )
    required = canonical_worktree_path(config, metadata.branch)
    return (
        f"1. Move this worktree from `{active_worktree}` to `{required}` before any other delivery action.\n"
        "2. Rerun `ollija annotate-plan` after the move; this guide contains stale active-worktree paths until then.\n"
        "Ollija does not move or reject the worktree."
    )


def _production_cleanup_action(
    config: ProjectConfig,
    metadata: PlanMetadata,
    active_worktree: Path,
) -> str:
    if not is_canonical_worktree(config, active_worktree, metadata.branch):
        return (
            "11. Retain this noncanonical worktree. Ollija withholds the cleanup "
            "command until relocation and reannotation make the exact canonical "
            "target explicit."
        )
    root = quote(str(config.authority.repository_root))
    worktree = quote(str(active_worktree))
    return (
        "11. After step 10 succeeds, perform worktree cleanup as the final "
        "filesystem action:\n"
        f"    - From `{config.authority.repository_root}`, require "
        f"`{active_worktree}` to remain registered, clean, unlocked, and at the "
        "verified candidate SHA. If any guard fails, retain it and report the "
        "reason.\n"
        f"    - Run `git -C {root} worktree remove {worktree}` without `--force`.\n"
        "    - Preserve the local and remote feature branches. Continue final "
        "reporting from the authoritative repository root."
    )


def _delivery_actions(
    config: ProjectConfig,
    metadata: PlanMetadata,
    active_worktree: Path,
) -> str:
    tests = "\n".join(f"   - `{command}`" for command in config.delivery.test_commands)
    remote = quote(config.git.remote)
    staging_ref = quote(f"refs/heads/{config.git.staging_branch}")
    production_ref = quote(f"refs/heads/{config.git.production_branch}")
    base = (
        "1. Complete implementation and the plan's verification contract.\n"
        "2. Run the configured focused checks:\n"
        f"{tests}\n"
        "3. The parent workflow commits only this plan's changes, pushes the feature branch, and records the candidate SHA."
    )
    if not metadata.delivery_selected_by_user:
        return (
            "Target is not authorized until the owner selects it. "
            "Wait for a later explicit release request; do not commit, push, stage, or promote on this guide alone."
        )
    if metadata.delivery_target == "on-request":
        return (
            "Wait for a later explicit release request; creating or completing this plan does not authorize "
            "a commit, push, staging deployment, or production release."
        )
    staging = (
        "4. Fetch the remote staging lane: `git fetch "
        f"{remote} {staging_ref}`.\n"
        "5. Require the unchanged candidate SHA to be a fast-forward of that fetched remote ref, then push the "
        f"exact candidate SHA to `refs/heads/{config.git.staging_branch}` with the server-enforced fast-forward "
        f"command `git push {remote} <candidate-sha>:{staging_ref}`.\n"
        "6. Verify the remote staging ref resolves to the candidate SHA and the deployment for "
        f"`{config.environments['staging'].service}` reports that same SHA.\n"
        "7. Run staging checks. Stop here if they fail."
    )
    if metadata.delivery_target == "staging":
        return base + "\n" + staging
    return (
        base
        + "\n"
        + staging
        + "\n8. Only after staging passes, fetch the remote production lane: `git fetch "
        f"{remote} {production_ref}`.\n"
        "9. Require the same unchanged candidate SHA to be a fast-forward of that fetched remote ref, then push the "
        f"exact candidate SHA to `refs/heads/{config.git.production_branch}` with the server-enforced fast-forward "
        f"command `git push {remote} <candidate-sha>:{production_ref}`.\n"
        "10. Verify the remote production ref resolves to the candidate SHA and the deployment for "
        f"`{config.environments['production'].service}` reports that same SHA before reporting completion.\n"
        + _production_cleanup_action(config, metadata, active_worktree)
    )


def _plan_only_verification(config: ProjectConfig) -> str:
    if not config.delivery.test_commands:
        return (
            "### Verification\n\n"
            "No project verification commands are configured. The parent implementation workflow "
            "must define and run checks appropriate to the change."
        )
    tests = "\n".join(f"- `{command}`" for command in config.delivery.test_commands)
    return f"### Verification\n\nRun the configured checks:\n\n{tests}"


def render_delivery_guide(
    config: ProjectConfig,
    *,
    plan_path: Path,
    active_worktree: Path,
    metadata: PlanMetadata,
) -> str:
    """Render one deterministic marker span from tracked inputs and plan metadata."""

    try:
        template = Template(config.template_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise AnnotationError(f"could not read delivery template: {config.template_path}") from exc
    values = {
        "profile": config.profile,
        "canonical_host": config.authority.canonical_host,
        "repository_root": str(config.authority.repository_root),
        "active_worktree": str(active_worktree),
        "plan_path": str(plan_path),
        "change_id": metadata.change_id,
        "branch": metadata.branch,
        "workflow": metadata.workflow,
        "delivery_target": metadata.delivery_target,
        "delivery_selected_by_user": str(metadata.delivery_selected_by_user).lower(),
        "code_failure_route": config.delivery.code_failure_route,
    }
    if config.has_delivery_profile:
        staging = config.environments["staging"]
        production = config.environments["production"]
        values.update(
            {
                "release_worktree_label": config.authority.release_worktree_label,
                "release_worktree_area": str(config.authority.release_worktree_area),
                "staging_branch": config.git.staging_branch,
                "staging_blueprint": str((active_worktree / staging.blueprint).resolve()),
                "production_branch": config.git.production_branch,
                "production_blueprint": str((active_worktree / production.blueprint).resolve()),
                "staging_url": staging.url,
                "production_url": production.url,
                "placement": _placement(config, metadata, active_worktree),
                "delivery_actions": _delivery_actions(config, metadata, active_worktree),
                "infra_failure_route": config.delivery.infra_failure_route,
            }
        )
    else:
        values["verification"] = _plan_only_verification(config)
    try:
        body = template.substitute(values).rstrip("\n")
    except (KeyError, ValueError) as exc:
        raise AnnotationError(f"delivery template has an invalid placeholder: {exc}") from exc
    return f"{BEGIN_MARKER}\n{body}\n{END_MARKER}"


def render_annotated_plan(
    original: str,
    *,
    config: ProjectConfig,
    plan_path: str | Path,
    active_worktree: str | Path,
) -> tuple[str, PlanMetadata]:
    """Return annotated content without writing it, for check-mode callers."""

    resolved_plan = Path(plan_path).expanduser().resolve()
    worktree = Path(active_worktree).expanduser().resolve()
    metadata = parse_plan_metadata(original)
    span = _marker_span(original)
    guide = render_delivery_guide(
        config, plan_path=resolved_plan, active_worktree=worktree, metadata=metadata
    )

    if span is None:
        _, insertion = _frontmatter_span(original)
        exceptions = (
            "" if _has_delivery_exceptions(original) else "\n\n## Delivery Exceptions\n\nNone.\n"
        )
        annotated = original[:insertion] + guide + exceptions + original[insertion:]
    else:
        start, end = span
        annotated = original[:start] + guide + original[end:]
        if not _has_delivery_exceptions(annotated):
            annotated = (
                annotated[: len(original[:start]) + len(guide)]
                + "\n\n## Delivery Exceptions\n\nNone.\n"
                + annotated[len(original[:start]) + len(guide) :]
            )

    return annotated, metadata
