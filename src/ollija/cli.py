"""The deliberately small public Ollija command surface."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

import yaml

from .annotate_plan import (
    AnnotationError,
    PlanMetadata,
    parse_plan_metadata,
    render_annotated_plan,
)
from .config import ConfigError, ProjectConfig, load_project_config
from .initialize import InitializationError, InitOptions, initialize_project
from .worktrees import WorktreeError, active_worktree_facts, canonical_worktree_path


class PlanDiscoveryError(ValueError):
    """A plan cannot be selected without risking a different change's plan."""


@dataclass(frozen=True, slots=True)
class ResolvedPlan:
    path: Path
    content: str
    metadata: PlanMetadata
    created: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ollija",
        description="Initialize a project and maintain one shared plan for its branch.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser(
        "init", help="Create a plan-only project contract and install the neutral agent skill."
    )
    initialize.add_argument(
        "--plans-directory",
        default="docs/plans",
        type=Path,
        help="Repository-relative plan directory to create (default: docs/plans).",
    )
    initialize.add_argument(
        "--remote", default="origin", help="Git remote used to derive repository identity."
    )
    initialize.add_argument(
        "--canonical-host", help="Repository host override; requires --repository-slug."
    )
    initialize.add_argument(
        "--repository-slug", help="Repository owner/name override; requires --canonical-host."
    )
    initialize.add_argument(
        "--test-command",
        action="append",
        default=[],
        help="Verification command to record; repeat for multiple commands.",
    )
    initialize.add_argument(
        "--skills-directory",
        type=Path,
        help="Shared user skill root (default: OLLIJA_SKILLS_DIRECTORY or ~/.agents/skills).",
    )
    initialize.add_argument(
        "--no-install-agent-skill",
        action="store_true",
        help="Create only the project contract and plan directory.",
    )
    annotate = commands.add_parser(
        "annotate-plan", help="Resolve or create, validate, and annotate one shared plan."
    )
    annotate.add_argument("plan_path", nargs="?", type=Path, metavar="PLAN")
    annotate.add_argument(
        "--check", action="store_true", help="Verify current content without writing."
    )
    annotate.add_argument("--workflow", help="Persist the selected workflow in plan metadata.")
    annotate.add_argument(
        "--delivery-target",
        choices=("on-request", "staging", "production"),
        help="Persist the owner-selected delivery target.",
    )
    annotate.add_argument(
        "--delivery-selected-by-user",
        action="store_true",
        help="Required with a staging or production delivery target.",
    )
    return parser


def _line(value: str | None, *, option: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise PlanDiscoveryError(f"{option}_must_be_a_non_empty_line")
    return value.strip()


def _yaml_scalar(value: str) -> str:
    """Serialize one already-validated line as a deterministic YAML scalar."""

    return yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=True,
        width=2**31 - 1,
    ).splitlines()[0]


def _plan_directory(config: ProjectConfig, active_worktree: Path) -> Path:
    directory = (active_worktree / config.plans.directory).resolve()
    if not directory.is_relative_to(active_worktree):
        raise PlanDiscoveryError("configured_plan_directory_outside_active_worktree")
    return directory


def _validate_explicit_path(path: Path, plan_directory: Path, active_worktree: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = active_worktree / candidate
    candidate = candidate.resolve()
    if candidate.suffix != ".md" or not candidate.is_relative_to(plan_directory):
        raise PlanDiscoveryError("explicit_plan_path_must_be_under_active_plan_directory")
    if not candidate.is_file():
        raise PlanDiscoveryError("explicit_plan_path_missing")
    return candidate


def _looks_like_ollija_plan(content: str) -> bool:
    return content.startswith("---") and re.search(r"(?m)^ollija:\s*(?:#.*)?$", content) is not None


def _read_plan(path: Path) -> tuple[str, PlanMetadata]:
    try:
        content = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PlanDiscoveryError(f"could_not_read_plan:{path}") from exc
    try:
        return content, parse_plan_metadata(content)
    except AnnotationError as exc:
        raise PlanDiscoveryError(f"malformed_plan:{path}:{exc}") from exc


def _matching_plans(plan_directory: Path, branch: str) -> list[ResolvedPlan]:
    if not plan_directory.exists():
        return []
    if not plan_directory.is_dir():
        raise PlanDiscoveryError("configured_plan_directory_is_not_a_directory")
    matches: list[ResolvedPlan] = []
    for candidate in sorted(plan_directory.rglob("*.md")):
        resolved = candidate.resolve()
        if not resolved.is_relative_to(plan_directory):
            raise PlanDiscoveryError(f"unsafe_plan_path:{candidate}")
        try:
            content = resolved.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PlanDiscoveryError(f"could_not_read_plan:{resolved}") from exc
        if not _looks_like_ollija_plan(content):
            continue
        try:
            metadata = parse_plan_metadata(content)
        except AnnotationError as exc:
            raise PlanDiscoveryError(f"malformed_plan:{resolved}:{exc}") from exc
        if metadata.branch == branch:
            matches.append(ResolvedPlan(resolved, content, metadata, False))
    return matches


def _stub(branch: str, *, workflow: str, target: str, selected: bool) -> tuple[str, PlanMetadata]:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    change_id = f"{branch.replace('/', '-')}-{timestamp}"
    metadata = PlanMetadata(change_id, branch, workflow, target, selected)
    content = f"""---
title: {_yaml_scalar(f"{branch} plan")}
artifact_contract: ce-unified-plan/v1
artifact_readiness: requirements-only
product_contract_source: ollija-annotate-plan
execution: code
ollija:
  change_id: {_yaml_scalar(change_id)}
  branch: {_yaml_scalar(branch)}
  workflow: {_yaml_scalar(workflow)}
  delivery_target: {_yaml_scalar(target)}
  delivery_selected_by_user: {str(selected).lower()}
---

# Goal

<!-- Planner: replace this requirements-only placeholder with the change goal. -->

## Product Contract

<!-- Planner: define the user-visible contract, acceptance cases, and verification. -->
"""
    return content, metadata


def _stub_name(branch: str, timestamp: str, attempt: int = 0) -> str:
    description = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-") or "plan"
    suffix = "" if attempt == 0 else f"-{attempt}"
    return f"{timestamp}-{description}-plan{suffix}.md"


def _metadata_with_inputs(metadata: PlanMetadata, args: argparse.Namespace) -> PlanMetadata:
    workflow = (
        metadata.workflow if args.workflow is None else _line(args.workflow, option="workflow")
    )
    if args.delivery_selected_by_user and args.delivery_target is None:
        raise PlanDiscoveryError("delivery_selected_by_user_requires_delivery_target")
    target = metadata.delivery_target if args.delivery_target is None else args.delivery_target
    selected = metadata.delivery_selected_by_user
    if args.delivery_target is not None:
        if (
            metadata.delivery_selected_by_user
            and metadata.delivery_target in {"staging", "production"}
            and args.delivery_target == "on-request"
        ):
            raise PlanDiscoveryError("selected_delivery_target_cannot_be_reset_to_on_request")
        selected = args.delivery_selected_by_user
    if target in {"staging", "production"} and not selected:
        raise PlanDiscoveryError("delivery_target_requires_explicit_user_selection")
    if target == "on-request" and selected:
        raise PlanDiscoveryError("on_request_delivery_target_cannot_be_user_selected")
    return replace(
        metadata, workflow=workflow, delivery_target=target, delivery_selected_by_user=selected
    )


def _replace_metadata(content: str, original: PlanMetadata, updated: PlanMetadata) -> str:
    if original == updated:
        return content
    closing = re.search(r"(?m)^(---|\.\.\.)\r?$", content[4:])
    if closing is None:
        raise PlanDiscoveryError("malformed_plan_frontmatter")
    frontmatter_end = 4 + closing.end()
    frontmatter = content[:frontmatter_end]
    lines = frontmatter.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.rstrip("\r\n") == "ollija:"), None
    )
    if start is None:
        raise PlanDiscoveryError("malformed_plan_ollija_mapping")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and line[0] not in " \t\r\n":
            end = index
            break
    replacements = {
        "workflow": _yaml_scalar(updated.workflow),
        "delivery_target": _yaml_scalar(updated.delivery_target),
        "delivery_selected_by_user": str(updated.delivery_selected_by_user).lower(),
    }
    seen: set[str] = set()
    for index in range(start + 1, end):
        match = re.match(
            r"^(\s+)(workflow|delivery_target|delivery_selected_by_user):[^\r\n]*(\r?\n?)$",
            lines[index],
        )
        if match:
            indent, key, newline = match.groups()
            lines[index] = f"{indent}{key}: {replacements[key]}{newline}"
            seen.add(key)
    if seen != replacements.keys():
        raise PlanDiscoveryError("malformed_plan_ollija_mapping")
    return "".join(lines) + content[frontmatter_end:]


def _exclusive_create(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise
    return True


def _atomic_replace(path: Path, content: str) -> None:
    """Replace an existing plan only after its complete new bytes are durable."""

    mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _resolve_plan(
    config: ProjectConfig,
    args: argparse.Namespace,
    active_worktree: Path,
    branch: str,
    *,
    write: bool,
) -> ResolvedPlan:
    directory = _plan_directory(config, active_worktree)
    if args.plan_path is not None:
        path = _validate_explicit_path(args.plan_path, directory, active_worktree)
        content, metadata = _read_plan(path)
        if metadata.branch != branch:
            raise PlanDiscoveryError("explicit_plan_branch_must_match_active_branch")
        return ResolvedPlan(path, content, metadata, False)
    matches = _matching_plans(directory, branch)
    if len(matches) > 1:
        raise PlanDiscoveryError("ambiguous_branch_plans_require_explicit_path")
    if matches:
        return matches[0]
    if not write:
        raise PlanDiscoveryError("plan_missing_for_branch")
    workflow = "plan" if args.workflow is None else _line(args.workflow, option="workflow")
    target = args.delivery_target or "on-request"
    selected = args.delivery_selected_by_user
    provisional = PlanMetadata("new", branch, workflow, target, selected)
    _metadata_with_inputs(provisional, args)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    for attempt in range(100):
        path = directory / _stub_name(branch, timestamp, attempt)
        if not path.exists():
            content, metadata = _stub(branch, workflow=workflow, target=target, selected=selected)
            return ResolvedPlan(path.resolve(), content, metadata, True)
    raise PlanDiscoveryError("could_not_create_unique_plan_stub")


def _lock(common_git_dir: Path, *, nonblocking: bool = False):
    # HEAD is a stable, shared Git file. Locking it avoids persistent Ollija
    # state while making no-path creation converge across linked worktrees.
    stream = (common_git_dir / "HEAD").open("r")
    try:
        operation = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
        fcntl.flock(stream.fileno(), operation)
    except BlockingIOError as exc:
        stream.close()
        raise PlanDiscoveryError("annotation_lock_busy_rerun_annotate_plan") from exc
    return stream


def _result(
    *,
    state: str,
    plan: ResolvedPlan,
    active_worktree: Path,
    config: ProjectConfig,
    branch: str,
    target: str,
) -> dict[str, str]:
    result = {
        "status": state,
        "result": state,
        "plan_path": str(plan.path),
        "active_worktree": str(active_worktree),
        "authoritative_root": str(config.authority.repository_root),
        "branch": branch,
        "delivery_target": target,
        "profile": config.profile,
    }
    if config.has_delivery_profile:
        result["canonical_required_path"] = str(canonical_worktree_path(config, branch))
    return result


def _annotate(args: argparse.Namespace, *, cwd: Path) -> dict[str, str]:
    project_root = os.environ.get("OLLIJA_PROJECT_ROOT")
    config = load_project_config(project_root or cwd)
    if config.profile == "plan-only" and (
        args.delivery_target not in {None, "on-request"} or args.delivery_selected_by_user
    ):
        raise PlanDiscoveryError("plan_only_profile_supports_on_request_delivery_only")
    facts = active_worktree_facts(cwd)
    hook_mode = os.environ.get("OLLIJA_HOOK_NONBLOCKING_LOCK") == "1"
    lock_stream = None if args.check else _lock(facts.common_git_dir, nonblocking=hook_mode)
    try:
        plan = _resolve_plan(
            config, args, facts.active_worktree, facts.branch, write=not args.check
        )
        metadata = _metadata_with_inputs(plan.metadata, args)
        if config.profile == "plan-only" and (
            metadata.delivery_target != "on-request" or metadata.delivery_selected_by_user
        ):
            raise PlanDiscoveryError("plan_only_profile_supports_on_request_delivery_only")
        base = _replace_metadata(plan.content, plan.metadata, metadata)
        try:
            annotated, _ = render_annotated_plan(
                base, config=config, plan_path=plan.path, active_worktree=facts.active_worktree
            )
        except AnnotationError as exc:
            raise PlanDiscoveryError(str(exc)) from exc
        changed = annotated != plan.content
        if args.check:
            if changed:
                raise PlanDiscoveryError("plan_annotation_stale_run_annotate_plan")
            state = "unchanged"
        else:
            if plan.created:
                if not _exclusive_create(plan.path, annotated):
                    raise PlanDiscoveryError("plan_stub_path_collision_retry_command")
            elif changed:
                _atomic_replace(plan.path, annotated)
            state = "created" if plan.created else ("updated" if changed else "unchanged")
        return _result(
            state=state,
            plan=plan,
            active_worktree=facts.active_worktree,
            config=config,
            branch=facts.branch,
            target=metadata.delivery_target,
        )
    finally:
        if lock_stream is not None:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
            lock_stream.close()


def main(
    argv: list[str] | None = None, *, cwd: Path | None = None, stream: TextIO | None = None
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    requested = os.environ.get("OLLIJA_WORKTREE_CWD")
    working_directory = Path(requested or cwd or Path.cwd()).resolve()
    try:
        result = (
            initialize_project(
                InitOptions(
                    plans_directory=args.plans_directory,
                    remote=args.remote,
                    canonical_host=args.canonical_host,
                    repository_slug=args.repository_slug,
                    test_commands=tuple(args.test_command),
                    skills_directory=args.skills_directory,
                    install_agent_skill=not args.no_install_agent_skill,
                ),
                cwd=working_directory,
            )
            if args.command == "init"
            else _annotate(args, cwd=working_directory)
        )
    except (
        AnnotationError,
        ConfigError,
        InitializationError,
        PlanDiscoveryError,
        WorktreeError,
        OSError,
    ) as exc:
        output.write(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True) + "\n")
        return 2
    output.write(json.dumps(result, sort_keys=True) + "\n")
    return 0
