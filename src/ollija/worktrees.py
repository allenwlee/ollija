"""Git facts and placement rules for the plan annotator."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig

_GIT_TIMEOUT_ERROR = "git_command_timed_out"


class WorktreeError(ValueError):
    """The active checkout cannot safely identify one plan."""


@dataclass(frozen=True, slots=True)
class WorktreeFacts:
    active_worktree: Path
    branch: str
    common_git_dir: Path


def _git(*args: str, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(_GIT_TIMEOUT_ERROR) from exc
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise WorktreeError(detail or "git_worktree_facts_unavailable")
    return completed.stdout.strip()


def active_worktree_facts(cwd: str | Path) -> WorktreeFacts:
    """Return the active linked checkout, its named branch, and shared Git dir."""

    directory = Path(cwd).expanduser().resolve()
    try:
        top = Path(_git("rev-parse", "--show-toplevel", cwd=directory)).resolve()
    except WorktreeError as exc:
        if str(exc) == _GIT_TIMEOUT_ERROR:
            raise
        raise WorktreeError("active_worktree_unavailable") from exc
    try:
        branch = _git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=top)
    except WorktreeError as exc:
        if str(exc) == _GIT_TIMEOUT_ERROR:
            raise
        raise WorktreeError("detached_head_requires_named_branch") from exc
    if not branch:
        raise WorktreeError("detached_head_requires_named_branch")
    try:
        common = Path(
            _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=top)
        ).resolve()
    except WorktreeError as exc:
        if str(exc) == _GIT_TIMEOUT_ERROR:
            raise
        raise WorktreeError("shared_git_directory_unavailable") from exc
    return WorktreeFacts(top, branch, common)


def canonical_worktree_path(config: ProjectConfig, branch: str) -> Path:
    return (config.authority.release_worktree_area / branch).resolve()


def is_canonical_worktree(config: ProjectConfig, active_worktree: str | Path, branch: str) -> bool:
    return Path(active_worktree).expanduser().resolve() == canonical_worktree_path(config, branch)
