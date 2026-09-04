from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from . import PROJECT_CONTRACT_VERSION


class ConfigError(ValueError):
    """An actionable error in the tracked annotation contract."""


@dataclass(frozen=True, slots=True)
class AuthorityConfig:
    canonical_host: str
    repository_root: Path
    repository_slug: str
    release_worktree_label: str | None = None
    release_worktree_path: Path | None = None

    @property
    def release_worktree_area(self) -> Path:
        if self.release_worktree_path is None:
            raise ConfigError("plan-only contracts do not define a release worktree area")
        return (self.repository_root / self.release_worktree_path).resolve()


@dataclass(frozen=True, slots=True)
class PlansConfig:
    directory: Path


@dataclass(frozen=True, slots=True)
class GitConfig:
    remote: str
    staging_branch: str | None = None
    production_branch: str | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    blueprint: Path
    url: str
    service: str


@dataclass(frozen=True, slots=True)
class DeliveryConfig:
    template: Path
    test_commands: tuple[str, ...]
    code_failure_route: str
    infra_failure_route: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """The small, tracked input contract for deterministic plan annotation."""

    root: Path
    path: Path
    schema_version: int
    profile: str
    authority: AuthorityConfig
    plans: PlansConfig
    git: GitConfig
    environments: Mapping[str, EnvironmentConfig]
    delivery: DeliveryConfig

    @property
    def template_path(self) -> Path:
        """The template in this checkout, validated against the authority root."""

        return (self.root / self.delivery.template).resolve()

    @property
    def has_delivery_profile(self) -> bool:
        return self.profile == "delivery"


_BASE_TOP_LEVEL = {"schema_version", "authority", "plans", "git"}
_DELIVERY_TOP_LEVEL = _BASE_TOP_LEVEL | {"environments", "delivery"}
_PLAN_ONLY_TOP_LEVEL = _BASE_TOP_LEVEL | {"profile", "guidance"}
_BASE_AUTHORITY_FIELDS = {"canonical_host", "repository_slug"}
_DELIVERY_AUTHORITY_FIELDS = _BASE_AUTHORITY_FIELDS | {
    "repository_root",
    "release_worktree_label",
    "release_worktree_path",
}
_PLAN_FIELDS = {"directory"}
_DELIVERY_GIT_FIELDS = {"remote", "staging_branch", "production_branch"}
_PLAN_ONLY_GIT_FIELDS = {"remote"}
_ENVIRONMENT_FIELDS = {"blueprint", "url", "service"}
_DELIVERY_FIELDS = {"template", "test_commands", "code_failure_route", "infra_failure_route"}
_GUIDANCE_FIELDS = {"template", "test_commands", "code_failure_route"}


def _find_contract(start: Path) -> Path:
    resolved = start.expanduser().resolve()
    if resolved.is_file():
        if resolved.name == "project.yaml" and resolved.parent.name == ".ollija":
            return resolved
        resolved = resolved.parent

    for directory in (resolved, *resolved.parents):
        candidate = directory / ".ollija" / "project.yaml"
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"No .ollija/project.yaml found from {start}. "
        "Run from a checkout containing the tracked annotation contract."
    )


def _mapping(raw: Mapping[str, Any], key: str, *, parent: str = "project") -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise ConfigError(f"Project contract field {parent}.{key} must be a mapping")
    return value


def _string(raw: Mapping[str, Any], key: str, *, parent: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ConfigError(f"Project contract field {parent}.{key} must be a non-empty line")
    return value.strip()


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str], *, parent: str) -> None:
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        raise ConfigError(f"Project contract has unknown fields in {parent}: " + ", ".join(unknown))


def _relative_path(raw: Mapping[str, Any], key: str, *, parent: str, root: Path) -> Path:
    value = Path(_string(raw, key, parent=parent))
    if value.is_absolute() or ".." in value.parts or value == Path("."):
        raise ConfigError(
            f"Project contract field {parent}.{key} must be a repository-relative path"
        )
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root):
        raise ConfigError(
            f"Project contract field {parent}.{key} must resolve inside authority.repository_root"
        )
    return value


def _url(raw: Mapping[str, Any], key: str, *, parent: str) -> str:
    value = _string(raw, key, parent=parent)
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise ConfigError(
            f"Project contract field {parent}.{key} must be an HTTPS base URL"
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError(f"Project contract field {parent}.{key} must be an HTTPS base URL")
    return value.rstrip("/")


def _branch(raw: Mapping[str, Any], key: str, *, parent: str) -> str:
    value = _string(raw, key, parent=parent)
    path = Path(value)
    if value.startswith("/") or ".." in path.parts or value.endswith("/") or "//" in value:
        raise ConfigError(f"Project contract field {parent}.{key} must be a branch name")
    return value


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"could not read project contract: {path}") from exc
    try:
        loaded = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise ConfigError(f"{path} must contain a YAML mapping")
    return loaded


def load_project_config(start: str | Path = ".") -> ProjectConfig:
    path = _find_contract(Path(start))
    root = path.parent.parent.resolve()
    raw = dict(_load_yaml(path))

    version = raw.get("schema_version")
    if version != PROJECT_CONTRACT_VERSION:
        raise ConfigError(
            f"Unsupported project contract version {version!r}; "
            f"this ollija supports version {PROJECT_CONTRACT_VERSION}."
        )
    profile = raw.get("profile", "delivery")
    if not isinstance(profile, str) or profile not in {"plan-only", "delivery"}:
        raise ConfigError("Project contract field profile must be plan-only or delivery")
    allowed_top_level = (
        _PLAN_ONLY_TOP_LEVEL if profile == "plan-only" else _DELIVERY_TOP_LEVEL | {"profile"}
    )
    required_top_level = _PLAN_ONLY_TOP_LEVEL if profile == "plan-only" else _DELIVERY_TOP_LEVEL
    missing = sorted(required_top_level - raw.keys())
    unknown = sorted(raw.keys() - allowed_top_level)
    if missing:
        raise ConfigError("Project contract is missing: " + ", ".join(missing))
    if unknown:
        raise ConfigError("Project contract has unknown fields: " + ", ".join(unknown))

    authority_raw = _mapping(raw, "authority")
    authority_fields = (
        _BASE_AUTHORITY_FIELDS if profile == "plan-only" else _DELIVERY_AUTHORITY_FIELDS
    )
    _reject_unknown(authority_raw, authority_fields, parent="authority")
    if profile == "delivery":
        repository_root = Path(_string(authority_raw, "repository_root", parent="authority"))
        if not repository_root.is_absolute():
            raise ConfigError("authority.repository_root must be absolute")
        repository_root = repository_root.resolve()
    else:
        repository_root = root
    authority = AuthorityConfig(
        canonical_host=_string(authority_raw, "canonical_host", parent="authority"),
        repository_root=repository_root,
        repository_slug=_string(authority_raw, "repository_slug", parent="authority"),
        release_worktree_label=(
            _string(authority_raw, "release_worktree_label", parent="authority")
            if profile == "delivery"
            else None
        ),
        release_worktree_path=(
            _relative_path(
                authority_raw,
                "release_worktree_path",
                parent="authority",
                root=repository_root,
            )
            if profile == "delivery"
            else None
        ),
    )

    plans_raw = _mapping(raw, "plans")
    _reject_unknown(plans_raw, _PLAN_FIELDS, parent="plans")
    plans = PlansConfig(
        directory=_relative_path(plans_raw, "directory", parent="plans", root=repository_root)
    )

    git_raw = _mapping(raw, "git")
    git_fields = _PLAN_ONLY_GIT_FIELDS if profile == "plan-only" else _DELIVERY_GIT_FIELDS
    _reject_unknown(git_raw, git_fields, parent="git")
    git = GitConfig(
        remote=_string(git_raw, "remote", parent="git"),
        staging_branch=(
            _branch(git_raw, "staging_branch", parent="git") if profile == "delivery" else None
        ),
        production_branch=(
            _branch(git_raw, "production_branch", parent="git") if profile == "delivery" else None
        ),
    )
    if profile == "delivery" and git.staging_branch == git.production_branch:
        raise ConfigError("git.staging_branch and git.production_branch must differ")

    environments: dict[str, EnvironmentConfig] = {}
    if profile == "delivery":
        environments_raw = _mapping(raw, "environments")
        for name in ("staging", "production"):
            environment = _mapping(environments_raw, name, parent="environments")
            _reject_unknown(environment, _ENVIRONMENT_FIELDS, parent=f"environments.{name}")
            environments[name] = EnvironmentConfig(
                blueprint=_relative_path(
                    environment,
                    "blueprint",
                    parent=f"environments.{name}",
                    root=repository_root,
                ),
                url=_url(environment, "url", parent=f"environments.{name}"),
                service=_string(environment, "service", parent=f"environments.{name}"),
            )
        unknown_environments = sorted(set(environments_raw) - set(environments))
        if unknown_environments:
            raise ConfigError(
                "Project contract has unknown environments: " + ", ".join(unknown_environments)
            )

    delivery_key = "guidance" if profile == "plan-only" else "delivery"
    delivery_raw = _mapping(raw, delivery_key)
    delivery_fields = _GUIDANCE_FIELDS if profile == "plan-only" else _DELIVERY_FIELDS
    _reject_unknown(delivery_raw, delivery_fields, parent=delivery_key)
    template = _relative_path(
        delivery_raw,
        "template",
        parent=delivery_key,
        root=repository_root,
    )
    commands = delivery_raw.get("test_commands")
    if (
        not isinstance(commands, list)
        or (profile == "delivery" and not commands)
        or not all(
            isinstance(command, str) and command.strip() and "\n" not in command
            for command in commands
        )
    ):
        requirement = "a list" if profile == "plan-only" else "a non-empty list"
        raise ConfigError(
            f"Project contract field {delivery_key}.test_commands must be {requirement}"
        )
    delivery = DeliveryConfig(
        template=template,
        test_commands=tuple(command.strip() for command in commands),
        code_failure_route=_string(delivery_raw, "code_failure_route", parent=delivery_key),
        infra_failure_route=(
            _string(delivery_raw, "infra_failure_route", parent="delivery")
            if profile == "delivery"
            else None
        ),
    )
    template_path = (root / delivery.template).resolve()
    if not template_path.is_file():
        raise ConfigError(f"Configured delivery template is missing: {template_path}")

    return ProjectConfig(
        root=root,
        path=path,
        schema_version=version,
        profile=profile,
        authority=authority,
        plans=plans,
        git=git,
        environments=environments,
        delivery=delivery,
    )
