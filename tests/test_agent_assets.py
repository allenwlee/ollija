from __future__ import annotations

import importlib.resources
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ollija.config import load_project_config

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "project"


def test_distributed_agent_assets_expose_only_the_supported_command() -> None:
    skill = (EXAMPLE_ROOT / "agent-skills" / "ollija" / "SKILL.md").read_text(encoding="utf-8")
    prompt = (EXAMPLE_ROOT / "agent-skills" / "ollija" / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )

    assert "ollija init" in skill
    assert "ollija annotate-plan" in skill
    assert "ollija init" in prompt
    assert "ollija annotate-plan" in prompt
    assert "./bin/ollija" not in skill + prompt
    for retired in ("ollija status", "ollija go", "ollija release", "ollija stop"):
        assert retired not in skill + prompt

    packaged = importlib.resources.files("ollija").joinpath("assets", "agent-skills", "ollija")
    assert packaged.joinpath("SKILL.md").read_text(encoding="utf-8") == skill
    assert packaged.joinpath("agents", "openai.yaml").read_text(encoding="utf-8") == prompt


def test_example_contract_loads_after_replacing_consumer_placeholders(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    shutil.copytree(EXAMPLE_ROOT / ".ollija", consumer / ".ollija")
    contract = consumer / ".ollija" / "project.yaml"
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "__ABSOLUTE_REPOSITORY_ROOT__", str(consumer.resolve())
        ),
        encoding="utf-8",
    )

    config = load_project_config(consumer)

    assert config.root == consumer
    assert config.authority.repository_slug == "example/project"
    assert config.environments["staging"].url == "https://staging.example.invalid"


def test_readme_setup_uses_installed_command_and_copyable_assets(tmp_path: Path) -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "uv tool install git+https://github.com/allenwlee/ollija.git" in readme
    assert 'uv tool install "$OLLIJA_CHECKOUT"' not in readme
    assert "uv tool install --editable" not in readme
    assert "ollija init" in readme
    assert "--plans-directory" in readme
    assert "ollija annotate-plan" in readme
    assert "ollija annotate-plan path/to/returned-plan.md --check" in readme
    assert "POSIX" in readme
    assert 'Ollija (올리자) in Korean dev-speak means, "Let\'s deploy!"' in readme

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    subprocess.run(("git", "init", "-b", "feat/readme", str(consumer)), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(consumer),
            "remote",
            "add",
            "origin",
            "https://github.com/example/consumer.git",
        ),
        check=True,
    )
    executable = Path(sys.executable).with_name("ollija")
    initialized = subprocess.run(
        (
            str(executable),
            "init",
            "--skills-directory",
            str(tmp_path / "skills"),
        ),
        cwd=consumer,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(initialized.stdout)["status"] == "created"
    created = subprocess.run(
        (str(executable), "annotate-plan"),
        cwd=consumer,
        check=True,
        capture_output=True,
        text=True,
    )
    plan = Path(json.loads(created.stdout)["plan_path"])

    assert "<!-- BEGIN OLLIJA DELIVERY GUIDE -->" in plan.read_text(encoding="utf-8")
    subprocess.run(
        (str(executable), "annotate-plan", "--check"),
        cwd=consumer,
        check=True,
        capture_output=True,
        text=True,
    )


def test_hook_reports_missing_installed_command_without_blocking(tmp_path: Path) -> None:
    hook = EXAMPLE_ROOT / ".ollija" / "hooks" / "post-checkout"
    repository = tmp_path / "repository"
    linked = tmp_path / "linked"
    subprocess.run(("git", "init", "-b", "main", str(repository)), check=True, capture_output=True)
    subprocess.run(("git", "-C", str(repository), "config", "user.name", "Test User"), check=True)
    subprocess.run(
        ("git", "-C", str(repository), "config", "user.email", "test@example.invalid"),
        check=True,
    )
    (repository / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(repository), "add", "README.md"), check=True)
    subprocess.run(("git", "-C", str(repository), "commit", "-m", "initial"), check=True)
    subprocess.run(
        ("git", "-C", str(repository), "worktree", "add", "-b", "feat/example", str(linked)),
        check=True,
        capture_output=True,
    )

    result = subprocess.run(
        ("/bin/sh", str(hook)),
        cwd=linked,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "ollija command is not installed" in result.stderr
