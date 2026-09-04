from __future__ import annotations

from pathlib import Path

import pytest

from ollija.config import ConfigError, load_project_config


def _write_config(root: Path, *, schema_version: int = 1) -> Path:
    config_dir = root / ".ollija"
    (config_dir / "templates").mkdir(parents=True)
    config_path = config_dir / "project.yaml"
    config_path.write_text(
        f"""\
schema_version: {schema_version}
authority:
  canonical_host: example-host
  repository_root: {root}
  repository_slug: example/project
  release_worktree_label: Ollija release worktree area
  release_worktree_path: .worktrees
plans:
  directory: docs/plans
git:
  remote: origin
  staging_branch: staging
  production_branch: main
environments:
  staging:
    blueprint: deploy/staging.yaml
    url: https://staging.example.invalid
    service: example-staging
  production:
    blueprint: deploy/production.yaml
    url: https://www.example.invalid
    service: example-production
delivery:
  template: .ollija/templates/delivery-guide.md
  test_commands: [pytest tests/ollija]
  code_failure_route: parent workflow
  infra_failure_route: infra/multi-machine skill
""",
        encoding="utf-8",
    )
    (config_dir / "templates" / "delivery-guide.md").write_text("guide\n", encoding="utf-8")
    return config_path


def test_project_contract_loads_annotation_facts_from_nested_directory(tmp_path: Path) -> None:
    _write_config(tmp_path)
    nested = tmp_path / "nested" / "directory"
    nested.mkdir(parents=True)
    config = load_project_config(nested)

    assert config.root == tmp_path
    assert config.schema_version == 1
    assert config.profile == "delivery"
    assert config.authority.canonical_host == "example-host"
    assert config.authority.release_worktree_label == "Ollija release worktree area"
    assert config.authority.release_worktree_path == Path(".worktrees")
    assert config.plans.directory == Path("docs/plans")
    assert config.git.remote == "origin"
    assert config.git.production_branch == "main"
    assert config.git.staging_branch == "staging"
    assert config.environments["staging"].url == "https://staging.example.invalid"
    assert config.template_path == tmp_path / ".ollija" / "templates" / "delivery-guide.md"


def test_missing_project_contract_is_actionable_and_read_only(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"No \.ollija/project\.yaml"):
        load_project_config(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_malformed_unknown_and_unsafe_contracts_fail_actionably(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    config_dir = malformed / ".ollija"
    config_dir.mkdir()
    (config_dir / "project.yaml").write_text("schema_version: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="valid YAML"):
        load_project_config(malformed)

    unknown = tmp_path / "unknown"
    unknown.mkdir()
    _write_config(unknown, schema_version=99)
    with pytest.raises(ConfigError, match="Unsupported project contract version 99"):
        load_project_config(unknown)

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    unsafe_path = _write_config(unsafe)
    unsafe_path.write_text(
        unsafe_path.read_text(encoding="utf-8").replace(
            "schema_version: 1", "schema_version: !!python/object/apply:os.system ['false']"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="valid YAML"):
        load_project_config(unsafe)


def test_non_utf8_contract_fails_with_a_stable_config_error(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    config_path.write_bytes(b"\xff\xfe")

    with pytest.raises(ConfigError, match="could not read project contract"):
        load_project_config(tmp_path)


def test_contract_rejects_a_non_string_profile_with_a_stable_error(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "schema_version: 1", "schema_version: 1\nprofile: []", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="profile must be plan-only or delivery"):
        load_project_config(tmp_path)


@pytest.mark.parametrize(
    ("anchor", "injected", "parent"),
    [
        ("  canonical_host: example-host", "  unexpected: value", "authority"),
        ("  directory: docs/plans", "  unexpected: value", "plans"),
        ("  remote: origin", "  unexpected: value", "git"),
        ("    service: example-staging", "    unexpected: value", "environments.staging"),
        ("  template: .ollija/templates/delivery-guide.md", "  unexpected: value", "delivery"),
    ],
)
def test_contract_rejects_unknown_nested_fields(
    tmp_path: Path, anchor: str, injected: str, parent: str
) -> None:
    config_path = _write_config(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(anchor, f"{anchor}\n{injected}", 1),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=rf"unknown fields in {parent}: unexpected"):
        load_project_config(tmp_path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("directory: docs/plans", "directory: ../plans", "repository-relative"),
        (
            "release_worktree_path: .worktrees",
            "release_worktree_path: /tmp/worktrees",
            "repository-relative",
        ),
        (
            "blueprint: deploy/staging.yaml",
            "blueprint: ../deploy/production.yaml",
            "repository-relative",
        ),
        (
            "url: https://staging.example.invalid",
            "url: http://staging.example.com",
            "HTTPS base URL",
        ),
    ],
)
def test_contract_rejects_paths_or_urls_outside_annotation_authority(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    config_path = _write_config(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match=message):
        load_project_config(tmp_path)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@staging.example.invalid",
        "https://staging.example.invalid?token=value",
        "https://staging.example.invalid#fragment",
        "https://staging.example.invalid/extra",
        "https://[invalid",
    ],
)
def test_contract_rejects_values_that_are_not_https_base_urls(tmp_path: Path, url: str) -> None:
    config_path = _write_config(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("https://staging.example.invalid", url, 1),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="HTTPS base URL"):
        load_project_config(tmp_path)


def test_contract_rejects_legacy_stateful_fields(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write("state: {directory: .ollija/state}\n")

    with pytest.raises(ConfigError, match="unknown fields: state"):
        load_project_config(tmp_path)
