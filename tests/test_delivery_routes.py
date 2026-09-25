from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from conftest import write_repository

from ollija.cli import main


def invoke(root: Path, *arguments: str) -> tuple[int, dict]:
    stream = io.StringIO()
    code = main(["annotate-plan", *arguments], cwd=root, stream=stream)
    return code, json.loads(stream.getvalue())


def test_direct_production_survives_resume_without_staging_mutations(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/independent")
    code, result = invoke(
        root,
        "--delivery-target",
        "production",
        "--delivery-selected-by-user",
        "--delivery-route",
        "direct",
        "--delivery-route-selected-by-user",
    )
    assert code == 0
    plan = Path(result["plan_path"])
    content = plan.read_bytes()
    assert b"refs/heads/main" in content
    assert b"refs/heads/staging" not in content
    assert b"Only after staging passes" not in content
    assert invoke(root)[1]["status"] == "unchanged"
    assert invoke(root, str(plan), "--check")[0] == 0
    assert plan.read_bytes() == content


def test_exact_commit_staging_does_not_require_branch_ancestry(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/commit-staging")
    code, result = invoke(
        root,
        "--delivery-target",
        "production",
        "--delivery-selected-by-user",
        "--delivery-route",
        "staged",
        "--delivery-route-selected-by-user",
        "--staging-transport",
        "commit",
    )
    assert code == 0
    content = Path(result["plan_path"]).read_text()
    assert "without moving its branch" in content
    assert "Do not interrupt another release" in content
    assert "refs/heads/staging" not in content
    assert "Only after staging passes" in content


@pytest.mark.parametrize("arguments", [(), ("--check",)])
def test_disabled_minimal_plan_is_unchanged_and_never_replaced(tmp_path: Path, arguments) -> None:
    root = write_repository(tmp_path, branch="feat/optout")
    plan = root / "docs/plans/owner.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    original = (
        b"---\r\nollija:\r\n  enabled: false\r\n  branch: feat/optout\r\n---\r\nOwner text.\r\n"
    )
    plan.write_bytes(original)
    code, result = invoke(root, *arguments)
    assert code == 0
    assert result["status"] == "disabled"
    assert result["plan_path"] == str(plan)
    assert plan.read_bytes() == original
    assert list(plan.parent.glob("*.md")) == [plan]
    assert invoke(root, str(plan), *arguments)[1]["status"] == "disabled"


@pytest.mark.parametrize(
    "arguments",
    [
        ("--delivery-route", "direct"),
        ("--delivery-route", "direct", "--delivery-route-selected-by-user"),
        (
            "--delivery-target",
            "staging",
            "--delivery-selected-by-user",
            "--delivery-route",
            "direct",
            "--delivery-route-selected-by-user",
        ),
        (
            "--delivery-target",
            "production",
            "--delivery-selected-by-user",
            "--delivery-route",
            "direct",
            "--delivery-route-selected-by-user",
            "--staging-transport",
            "commit",
        ),
    ],
)
def test_route_cannot_invent_authority_or_contradict_target(tmp_path: Path, arguments) -> None:
    root = write_repository(tmp_path, branch="feat/no-grant")
    code, _ = invoke(root, *arguments)
    assert code == 2
    assert not list((root / "docs/plans").glob("*.md"))


def test_direct_route_can_return_to_commit_staging_with_new_selection(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/change-route")
    assert (
        invoke(
            root,
            "--delivery-target",
            "production",
            "--delivery-selected-by-user",
            "--delivery-route",
            "direct",
            "--delivery-route-selected-by-user",
        )[0]
        == 0
    )
    code, result = invoke(
        root,
        "--delivery-route",
        "staged",
        "--delivery-route-selected-by-user",
        "--staging-transport",
        "commit",
    )
    assert code == 0
    content = Path(result["plan_path"]).read_text()
    assert "Only after staging passes" in content
    assert "without moving its branch" in content
    assert invoke(root, "--check")[0] == 0


def test_route_update_preserves_existing_mapping_indentation(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/indent")
    _, result = invoke(root)
    plan = Path(result["plan_path"])
    frontmatter, body = plan.read_text().split("---", 2)[1:]
    frontmatter = "\n".join(
        "  " + line if line.startswith("  ") else line for line in frontmatter.split("\n")
    )
    plan.write_text("---" + frontmatter + "---" + body)
    code, _ = invoke(
        root,
        "--delivery-target",
        "production",
        "--delivery-selected-by-user",
        "--delivery-route",
        "direct",
        "--delivery-route-selected-by-user",
    )
    assert code == 0
    assert "    delivery_route: direct\n" in plan.read_text()
    assert invoke(root, "--check")[0] == 0


def test_checkout_hook_preserves_disabled_plan(tmp_path: Path, monkeypatch) -> None:
    import os
    import shutil
    import sys

    from conftest import REPO_ROOT, run_git

    root = write_repository(tmp_path, branch="feat/hook-source")
    plan = root / "docs/plans/optout.md"
    plan.parent.mkdir(parents=True)
    original = b"---\nollija:\n  enabled: false\n  branch: feat/hook-optout\n---\nOwner text.\n"
    plan.write_bytes(original)
    hook = root / ".ollija/hooks/post-checkout"
    hook.parent.mkdir(parents=True)
    shutil.copy(REPO_ROOT / "examples/project/.ollija/hooks/post-checkout", hook)
    hook.chmod(0o755)
    run_git(root, "add", ".ollija", "docs/plans")
    run_git(root, "commit", "-m", "disabled plan and hook")
    run_git(root, "config", "core.hooksPath", str(hook.parent))
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    worktree = tmp_path / "linked"
    checkout = run_git(root, "worktree", "add", "-b", "feat/hook-optout", str(worktree))
    assert '"status": "disabled"' in checkout.stdout + checkout.stderr
    assert (worktree / "docs/plans/optout.md").read_bytes() == original
    assert list((worktree / "docs/plans").glob("*.md")) == [worktree / "docs/plans/optout.md"]
