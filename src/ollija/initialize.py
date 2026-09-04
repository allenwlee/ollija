"""Deterministic, conflict-safe project and agent-skill initialization."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.resources
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

from . import PROJECT_CONTRACT_VERSION
from .config import load_project_config
from .worktrees import active_worktree_facts


class InitializationError(ValueError):
    """A project or user skill cannot be initialized without overwriting data."""


@dataclass(frozen=True, slots=True)
class InitOptions:
    plans_directory: Path
    remote: str
    canonical_host: str | None
    repository_slug: str | None
    test_commands: tuple[str, ...]
    skills_directory: Path | None
    install_agent_skill: bool


def _line(value: str | None, *, option: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise InitializationError(f"{option}_must_be_a_non_empty_line")
    return value.strip()


def _yaml_scalar(value: str) -> str:
    return yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=True,
        width=2**31 - 1,
    ).splitlines()[0]


def _relative_directory(value: Path, *, option: str, root: Path) -> Path:
    if value.is_absolute() or value == Path(".") or ".." in value.parts:
        raise InitializationError(f"{option}_must_be_a_repository_relative_directory")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root):
        raise InitializationError(f"{option}_must_resolve_inside_repository")
    return value


def _remote_identity(remote_url: str) -> tuple[str, str] | None:
    value = remote_url.strip()
    match = re.fullmatch(r"(?:[^@/:]+@)?([^/:]+):(.+)", value)
    if match and "://" not in value:
        host, path = match.groups()
    else:
        try:
            parsed = urlparse(value)
        except ValueError:
            return None
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname:
            return None
        host, path = parsed.hostname, parsed.path
    slug = path.strip("/")
    if slug.endswith(".git"):
        slug = slug[:-4]
    parts = slug.split("/")
    if len(parts) < 2 or any(not part or part in {".", ".."} for part in parts):
        return None
    return host, "/".join(parts)


def _git_output(*args: str, cwd: Path) -> str:
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
        raise InitializationError("git_command_timed_out") from exc
    if completed.returncode:
        raise InitializationError(
            "repository_identity_unavailable_pass_canonical_host_and_repository_slug"
        )
    return completed.stdout.strip()


def _repository_identity(options: InitOptions, *, root: Path) -> tuple[str, str]:
    host = options.canonical_host
    slug = options.repository_slug
    if (host is None) != (slug is None):
        raise InitializationError("canonical_host_and_repository_slug_must_be_supplied_together")
    if host is not None and slug is not None:
        return _line(host, option="canonical_host"), _line(slug, option="repository_slug")
    remote = _line(options.remote, option="remote")
    identity = _remote_identity(_git_output("remote", "get-url", remote, cwd=root))
    if identity is None:
        raise InitializationError(
            "repository_identity_unavailable_pass_canonical_host_and_repository_slug"
        )
    return identity


def _asset_text(*parts: str) -> str:
    try:
        return (
            importlib.resources.files("ollija")
            .joinpath("assets", *parts)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError, UnicodeError) as exc:
        raise InitializationError("installed_ollija_assets_are_unavailable") from exc


def _plan_only_contract(
    *,
    host: str,
    slug: str,
    remote: str,
    plans_directory: Path,
    test_commands: tuple[str, ...],
) -> str:
    commands = "[]"
    if test_commands:
        commands = "\n" + "\n".join(
            f"    - {_yaml_scalar(_line(command, option='test_command'))}"
            for command in test_commands
        )
    return f"""\
schema_version: {PROJECT_CONTRACT_VERSION}
profile: plan-only
authority:
  canonical_host: {_yaml_scalar(host)}
  repository_slug: {_yaml_scalar(slug)}
plans:
  directory: {_yaml_scalar(str(plans_directory))}
git:
  remote: {_yaml_scalar(remote)}
guidance:
  template: .ollija/templates/plan-guide.md
  test_commands: {commands}
  code_failure_route: parent implementation workflow
"""


def _skill_assets() -> dict[Path, bytes]:
    return {
        Path("SKILL.md"): _asset_text("agent-skills", "ollija", "SKILL.md").encode("utf-8"),
        Path("agents/openai.yaml"): _asset_text(
            "agent-skills", "ollija", "agents", "openai.yaml"
        ).encode("utf-8"),
    }


def _skill_manifest(assets: dict[Path, bytes]) -> bytes:
    hashes = {
        str(path): hashlib.sha256(content).hexdigest()
        for path, content in sorted(assets.items(), key=lambda item: str(item[0]))
    }
    return (json.dumps({"files": hashes, "schema_version": 1}, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _read_skill_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InitializationError("agent_skill_manifest_is_invalid") from exc
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != 1
        or set(raw) != {"files", "schema_version"}
        or not isinstance(raw["files"], dict)
        or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in raw["files"].items()
        )
    ):
        raise InitializationError("agent_skill_manifest_is_invalid")
    return raw["files"]


def _has_symlink(root: Path, target: Path) -> bool:
    current = root
    for part in target.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _preflight_skill(skill_root: Path, assets: dict[Path, bytes]) -> None:
    if skill_root.is_symlink():
        raise InitializationError("agent_skill_target_conflicts:.")
    manifest_path = skill_root / ".ollija-managed.json"
    if _has_symlink(skill_root, manifest_path):
        raise InitializationError("agent_skill_target_conflicts:.ollija-managed.json")
    manifest = _read_skill_manifest(manifest_path)
    for relative, desired in assets.items():
        target = skill_root / relative
        if _has_symlink(skill_root, target):
            raise InitializationError(f"agent_skill_target_conflicts:{relative}")
        if not target.exists():
            continue
        if not target.is_file():
            raise InitializationError(f"agent_skill_target_conflicts:{relative}")
        try:
            current = target.read_bytes()
        except OSError as exc:
            raise InitializationError(f"could_not_read_agent_skill_target:{relative}") from exc
        if current == desired:
            continue
        expected_hash = manifest.get(str(relative))
        if expected_hash is None or hashlib.sha256(current).hexdigest() != expected_hash:
            raise InitializationError(f"agent_skill_target_conflicts:{relative}")


def _write_bytes(path: Path, content: bytes) -> bool:
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            if path.is_file() and path.read_bytes() == content:
                return False
            raise InitializationError(f"initialization_target_changed:{path.name}") from None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
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
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return True


def _install_skill(skill_root: Path, assets: dict[Path, bytes]) -> str:
    existed = (
        any((skill_root / relative).exists() for relative in assets)
        or (skill_root / ".ollija-managed.json").exists()
    )
    changed = False
    for relative, content in assets.items():
        changed = _write_bytes(skill_root / relative, content) or changed
    changed = _write_bytes(skill_root / ".ollija-managed.json", _skill_manifest(assets)) or changed
    if not changed:
        return "unchanged"
    return "updated" if existed else "created"


def _lock(common_git_dir: Path):
    stream = (common_git_dir / "HEAD").open("r")
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    return stream


def _skill_lock(skills_directory: Path):
    descriptor: int | None = None
    stream = None
    try:
        skills_directory.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(skills_directory / ".ollija-init.lock", flags, 0o600)
        stream = os.fdopen(descriptor, "r+")
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    except OSError as exc:
        if stream is not None:
            stream.close()
        elif descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        raise InitializationError("agent_skill_lock_unavailable") from exc
    return stream


def initialize_project(options: InitOptions, *, cwd: Path) -> dict[str, object]:
    facts = active_worktree_facts(cwd)
    root = facts.active_worktree
    contract_directory = root / ".ollija"
    contract_path = contract_directory / "project.yaml"
    project_files: dict[Path, bytes] = {}

    if contract_directory.is_symlink():
        raise InitializationError("initialization_target_conflicts:.ollija")
    if contract_path.is_symlink():
        raise InitializationError("initialization_target_conflicts:.ollija/project.yaml")
    if contract_path.exists():
        config = load_project_config(root)
        profile = config.profile
        plans_directory = config.plans.directory
        project_status = "unchanged"
    else:
        if (root / ".ollija").exists() and not (root / ".ollija").is_dir():
            raise InitializationError("initialization_target_conflicts:.ollija")
        plans_directory = _relative_directory(
            options.plans_directory,
            option="plans_directory",
            root=root,
        )
        remote = _line(options.remote, option="remote")
        host, slug = _repository_identity(options, root=root)
        template_path = root / ".ollija" / "templates" / "plan-guide.md"
        project_files = {
            template_path: _asset_text("templates", "plan-guide.md").encode("utf-8"),
            contract_path: _plan_only_contract(
                host=host,
                slug=slug,
                remote=remote,
                plans_directory=plans_directory,
                test_commands=options.test_commands,
            ).encode("utf-8"),
        }
        for target, desired in project_files.items():
            relative = target.relative_to(root)
            if _has_symlink(root, target):
                raise InitializationError(f"initialization_target_conflicts:{relative}")
            if not target.exists():
                continue
            if not target.is_file() or target.read_bytes() != desired:
                raise InitializationError(f"initialization_target_conflicts:{relative}")
        profile = "plan-only"
        project_status = "created"

    plan_directory = (root / plans_directory).resolve()
    if not plan_directory.is_relative_to(root):
        raise InitializationError("plans_directory_must_resolve_inside_repository")
    if plan_directory.exists() and not plan_directory.is_dir():
        raise InitializationError(f"initialization_target_conflicts:{plans_directory}")

    skill_root: Path | None = None
    skills_directory: Path | None = None
    skill_assets: dict[Path, bytes] = {}
    if options.install_agent_skill:
        configured_root = options.skills_directory or Path(
            os.environ.get("OLLIJA_SKILLS_DIRECTORY", "~/.agents/skills")
        )
        expanded_root = configured_root.expanduser()
        if not expanded_root.is_absolute():
            raise InitializationError("skills_directory_must_be_absolute")
        skills_directory = expanded_root.resolve()
        if skills_directory.exists() and not skills_directory.is_dir():
            raise InitializationError("skills_directory_must_be_a_directory")
        skill_root = skills_directory / "ollija"
        skill_assets = _skill_assets()
        _preflight_skill(skill_root, skill_assets)

    with ExitStack() as locks:
        locks.enter_context(_lock(facts.common_git_dir))
        if skills_directory is not None:
            locks.enter_context(_skill_lock(skills_directory))
        for target, desired in project_files.items():
            relative = target.relative_to(root)
            if _has_symlink(root, target) or (
                target.exists() and (not target.is_file() or target.read_bytes() != desired)
            ):
                raise InitializationError(f"initialization_target_conflicts:{relative}")
        if skill_root is not None:
            _preflight_skill(skill_root, skill_assets)

        for target, content in project_files.items():
            _write_bytes(target, content)
        plan_directory_existed = plan_directory.exists()
        plan_directory.mkdir(parents=True, exist_ok=True)
        if project_status == "unchanged" and not plan_directory_existed:
            project_status = "updated"
        skill_status = (
            _install_skill(skill_root, skill_assets) if skill_root is not None else "skipped"
        )

    if project_files:
        profile = load_project_config(root).profile

    return {
        "cli_status": "available" if shutil.which("ollija") else "python-module-only",
        "contract_path": str(contract_path),
        "plan_directory": str(plan_directory),
        "profile": profile,
        "project_root": str(root),
        "skill_path": str(skill_root / "SKILL.md") if skill_root is not None else None,
        "skill_status": skill_status,
        "status": project_status,
    }
