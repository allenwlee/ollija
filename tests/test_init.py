from __future__ import annotations

import concurrent.futures
import io
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
import yaml

from ollija import initialize
from ollija.cli import main
from ollija.config import ConfigError, load_project_config


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", "-C", str(root), *args), check=True, capture_output=True, text=True)


def _repository(tmp_path: Path, *, remote: str | None = None, name: str = "consumer") -> Path:
    root = tmp_path / name
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Example User")
    _git(root, "config", "user.email", "example@example.invalid")
    (root / "README.md").write_text("example\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "initial")
    _git(root, "checkout", "-b", "feat/example")
    if remote is not None:
        _git(root, "remote", "add", "origin", remote)
    return root


def _invoke(root: Path, *args: str) -> tuple[int, dict[str, object]]:
    stream = io.StringIO()
    code = main(list(args), cwd=root, stream=stream)
    return code, json.loads(stream.getvalue())


def _init(root: Path, skills: Path, *args: str) -> tuple[int, dict[str, object]]:
    return _invoke(root, "init", "--skills-directory", str(skills), *args)


def test_init_creates_a_plan_only_contract_and_is_repeatable(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    skills = tmp_path / "skills"

    code, created = _init(root, skills)

    assert code == 0
    assert created.pop("cli_status") in {"available", "python-module-only"}
    assert created == {
        "contract_path": str(root / ".ollija" / "project.yaml"),
        "plan_directory": str(root / "docs" / "plans"),
        "profile": "plan-only",
        "project_root": str(root),
        "skill_path": str(skills / "ollija" / "SKILL.md"),
        "skill_status": "created",
        "status": "created",
    }
    contract_path = root / ".ollija" / "project.yaml"
    template_path = root / ".ollija" / "templates" / "plan-guide.md"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    assert contract == {
        "schema_version": 1,
        "profile": "plan-only",
        "authority": {
            "canonical_host": "github.com",
            "repository_slug": "example/consumer",
        },
        "plans": {"directory": "docs/plans"},
        "git": {"remote": "origin"},
        "guidance": {
            "template": ".ollija/templates/plan-guide.md",
            "test_commands": [],
            "code_failure_route": "parent implementation workflow",
        },
    }
    assert template_path.is_file()
    assert (root / "docs" / "plans").is_dir()
    assert "ollija init" in (skills / "ollija" / "SKILL.md").read_text(encoding="utf-8")
    assert (skills / "ollija" / "agents" / "openai.yaml").is_file()
    config = load_project_config(root)
    assert config.profile == "plan-only"
    assert config.authority.repository_root == root
    assert config.git.staging_branch is None
    assert config.environments == {}

    before = {path.relative_to(root): path.read_bytes() for path in (contract_path, template_path)}
    skill_before = {
        path.relative_to(skills): path.read_bytes()
        for path in (skills / "ollija").rglob("*")
        if path.is_file()
    }
    code, unchanged = _init(root, skills)

    assert code == 0
    assert unchanged["status"] == "unchanged"
    assert unchanged["skill_status"] == "unchanged"
    assert {
        path.relative_to(root): path.read_bytes() for path in (contract_path, template_path)
    } == before
    assert {
        path.relative_to(skills): path.read_bytes()
        for path in (skills / "ollija").rglob("*")
        if path.is_file()
    } == skill_before


def test_initialized_plan_only_contract_derives_root_after_checkout_moves(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    assert _init(root, tmp_path / "skills")[0] == 0
    moved = tmp_path / "moved"
    shutil.copytree(root / ".ollija", moved / ".ollija")

    config = load_project_config(moved)

    assert config.root == moved
    assert config.authority.repository_root == moved


def test_plan_only_contract_rejects_a_persisted_checkout_path(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    assert _init(root, tmp_path / "skills")[0] == 0
    contract_path = root / ".ollija" / "project.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["authority"]["repository_root"] = str(root)
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown fields in authority: repository_root"):
        load_project_config(root)


def test_init_accepts_scp_remote_and_configurable_plan_directory(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="git@example.net:team/project.git")

    code, result = _init(root, tmp_path / "skills", "--plans-directory", "plans")

    assert code == 0
    contract = yaml.safe_load((root / ".ollija" / "project.yaml").read_text(encoding="utf-8"))
    assert contract["authority"]["canonical_host"] == "example.net"
    assert contract["authority"]["repository_slug"] == "team/project"
    assert contract["plans"]["directory"] == "plans"
    assert result["plan_directory"] == str(root / "plans")
    assert (root / "plans").is_dir()


def test_init_records_and_renders_configured_test_commands(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")

    code, _ = _init(
        root,
        tmp_path / "skills",
        "--test-command",
        "python -m pytest",
        "--test-command",
        "python -m ruff check .",
    )

    assert code == 0
    contract = yaml.safe_load((root / ".ollija" / "project.yaml").read_text(encoding="utf-8"))
    assert contract["guidance"]["test_commands"] == [
        "python -m pytest",
        "python -m ruff check .",
    ]
    code, result = _invoke(root, "annotate-plan")
    assert code == 0
    content = Path(str(result["plan_path"])).read_text(encoding="utf-8")
    assert content.index("`python -m pytest`") < content.index("`python -m ruff check .`")


def test_init_requires_explicit_identity_when_remote_cannot_supply_it(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    skills = tmp_path / "skills"

    code, missing = _init(root, skills)

    assert code == 2
    assert missing == {
        "error": "repository_identity_unavailable_pass_canonical_host_and_repository_slug",
        "status": "failed",
    }
    assert not (root / ".ollija").exists()

    code, created = _init(
        root,
        skills,
        "--canonical-host",
        "git.example.test",
        "--repository-slug",
        "team/local-project",
    )

    assert code == 0
    assert created["status"] == "created"


def test_init_refuses_conflicting_files_without_partial_writes(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    template = root / ".ollija" / "templates" / "plan-guide.md"
    template.parent.mkdir(parents=True)
    template.write_text("consumer-owned\n", encoding="utf-8")

    code, result = _init(root, tmp_path / "skills")

    assert code == 2
    assert result == {
        "error": "initialization_target_conflicts:.ollija/templates/plan-guide.md",
        "status": "failed",
    }
    assert template.read_text(encoding="utf-8") == "consumer-owned\n"
    assert not (root / ".ollija" / "project.yaml").exists()
    assert not (root / "docs" / "plans").exists()


def test_init_refuses_a_symlinked_project_contract_directory(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    external = tmp_path / "external-contract"
    external.mkdir()
    (root / ".ollija").symlink_to(external, target_is_directory=True)

    code, result = _init(root, tmp_path / "skills")

    assert code == 2
    assert result == {
        "error": "initialization_target_conflicts:.ollija",
        "status": "failed",
    }
    assert not list(external.iterdir())
    assert not (root / "docs" / "plans").exists()


def test_init_refuses_an_existing_unmanaged_agent_skill_before_project_writes(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    skill = tmp_path / "skills" / "ollija" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("consumer-owned\n", encoding="utf-8")

    code, result = _init(root, tmp_path / "skills")

    assert code == 2
    assert result == {
        "error": "agent_skill_target_conflicts:SKILL.md",
        "status": "failed",
    }
    assert skill.read_text(encoding="utf-8") == "consumer-owned\n"
    assert not (root / ".ollija").exists()
    assert not (root / "docs" / "plans").exists()


def test_init_refuses_a_symlinked_agent_skill_before_project_writes(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    skills = tmp_path / "skills"
    external = tmp_path / "external-skill"
    skills.mkdir()
    external.mkdir()
    (skills / "ollija").symlink_to(external, target_is_directory=True)

    code, result = _init(root, skills)

    assert code == 2
    assert result == {
        "error": "agent_skill_target_conflicts:.",
        "status": "failed",
    }
    assert not list(external.iterdir())
    assert not (root / ".ollija").exists()
    assert not (root / "docs" / "plans").exists()


def test_init_refuses_a_non_directory_skill_root_before_project_writes(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    skills = tmp_path / "skills"
    skills.write_text("consumer-owned\n", encoding="utf-8")

    code, result = _init(root, skills)

    assert code == 2
    assert result == {
        "error": "skills_directory_must_be_a_directory",
        "status": "failed",
    }
    assert skills.read_text(encoding="utf-8") == "consumer-owned\n"
    assert not (root / ".ollija").exists()
    assert not (root / "docs" / "plans").exists()


def test_init_serializes_shared_skill_updates_across_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _repository(
        tmp_path,
        remote="https://github.com/example/first.git",
        name="first",
    )
    second = _repository(
        tmp_path,
        remote="https://github.com/example/second.git",
        name="second",
    )
    skills = tmp_path / "skills"
    initial_preflights = threading.Barrier(2)
    thread_state = threading.local()
    install_guard = threading.Lock()
    concurrent_install = threading.Event()
    original_preflight = initialize._preflight_skill
    original_install = initialize._install_skill

    def synchronized_preflight(skill_root: Path, assets: dict[Path, bytes]) -> None:
        calls = getattr(thread_state, "preflight_calls", 0) + 1
        thread_state.preflight_calls = calls
        if calls == 1:
            initial_preflights.wait(timeout=2)
        original_preflight(skill_root, assets)

    def observed_install(skill_root: Path, assets: dict[Path, bytes]) -> str:
        acquired = install_guard.acquire(blocking=False)
        if not acquired:
            concurrent_install.set()
            install_guard.acquire()
        try:
            time.sleep(0.1)
            return original_install(skill_root, assets)
        finally:
            install_guard.release()

    monkeypatch.setattr(initialize, "_preflight_skill", synchronized_preflight)
    monkeypatch.setattr(initialize, "_install_skill", observed_install)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda root: _init(root, skills), (first, second)))

    assert [code for code, _ in results] == [0, 0]
    assert not concurrent_install.is_set()


def test_init_refreshes_only_an_unmodified_managed_agent_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    skills = tmp_path / "skills"
    assert _init(root, skills)[0] == 0
    original_assets = initialize._skill_assets()
    refreshed_assets = {
        **original_assets,
        Path("SKILL.md"): original_assets[Path("SKILL.md")] + b"\n<!-- refreshed -->\n",
    }
    monkeypatch.setattr(initialize, "_skill_assets", lambda: refreshed_assets)

    code, refreshed = _init(root, skills)

    assert code == 0
    assert refreshed["status"] == "unchanged"
    assert refreshed["skill_status"] == "updated"
    skill = skills / "ollija" / "SKILL.md"
    assert skill.read_bytes() == refreshed_assets[Path("SKILL.md")]

    skill.write_bytes(skill.read_bytes() + b"consumer edit\n")
    next_assets = {
        **refreshed_assets,
        Path("SKILL.md"): refreshed_assets[Path("SKILL.md")] + b"<!-- next -->\n",
    }
    monkeypatch.setattr(initialize, "_skill_assets", lambda: next_assets)

    code, conflict = _init(root, skills)

    assert code == 2
    assert conflict["error"] == "agent_skill_target_conflicts:SKILL.md"
    assert skill.read_bytes().endswith(b"consumer edit\n")


def test_plan_only_annotation_has_no_deployment_or_worktree_guidance(tmp_path: Path) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    assert _init(root, tmp_path / "skills")[0] == 0

    code, result = _invoke(root, "annotate-plan")

    assert code == 0
    plan = Path(str(result["plan_path"]))
    content = plan.read_text(encoding="utf-8")
    assert "Profile: `plan-only`" in content
    assert "No staging or production delivery authority" in content
    for forbidden in (
        "Staging branch",
        "Production branch",
        "worktree remove",
        "Move this worktree",
        "push the exact candidate SHA",
    ):
        assert forbidden not in content
    assert result["profile"] == "plan-only"
    assert "canonical_required_path" not in result


def test_plan_only_profile_rejects_deployment_targets_without_creating_a_plan(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, remote="https://github.com/example/consumer.git")
    assert _init(root, tmp_path / "skills")[0] == 0

    code, result = _invoke(
        root,
        "annotate-plan",
        "--delivery-target",
        "staging",
        "--delivery-selected-by-user",
    )

    assert code == 2
    assert result == {
        "error": "plan_only_profile_supports_on_request_delivery_only",
        "status": "failed",
    }
    assert not list((root / "docs" / "plans").glob("*.md"))
