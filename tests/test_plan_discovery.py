from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import run_git as _git
from conftest import write_repository

from ollija import cli
from ollija.cli import main

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def invoke(root: Path, *args: str) -> tuple[int, dict[str, str]]:
    stream = io.StringIO()
    code = main(["annotate-plan", *args], cwd=root, stream=stream)
    return code, json.loads(stream.getvalue())


def _plan(
    root: Path,
    name: str,
    branch: str,
    *,
    marker: str = "",
    target: str = "on-request",
    selected: bool = False,
) -> Path:
    path = root / "docs" / "plans" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        (
            "---",
            "title: Existing",
            "artifact_contract: ce-unified-plan/v1",
            "artifact_readiness: requirements-only",
            "execution: code",
            "ollija:",
            "  change_id: existing",
            f"  branch: {branch}",
            "  workflow: plan",
            f"  delivery_target: {target}",
            f"  delivery_selected_by_user: {str(selected).lower()}",
            "---",
            "",
            "# Goal",
            "",
            marker,
            "",
        )
    )
    path.write_text(content, encoding="utf-8")
    return path


def test_no_match_creates_a_valid_unified_plan_stub_and_reports_locations(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/new-plan")
    code, result = invoke(root)

    assert code == 0
    assert result["result"] == "created"
    assert result["status"] == "created"
    path = Path(result["plan_path"])
    content = path.read_text(encoding="utf-8")
    assert path.parent == root / "docs" / "plans"
    assert path.name.endswith("-feat-new-plan-plan.md")
    assert "artifact_contract: ce-unified-plan/v1" in content
    assert "artifact_readiness: requirements-only" in content
    assert "execution: code" in content
    assert "# Goal" in content and "## Product Contract" in content
    assert result["active_worktree"] == str(root)
    assert result["authoritative_root"] == str(root)
    assert result["branch"] == "feat/new-plan"
    assert result["canonical_required_path"] == str(root / ".worktrees" / "feat" / "new-plan")
    assert result["delivery_target"] == "on-request"


@pytest.mark.parametrize("branch", ("#evil", "&anchor", "!tag", "`reserved"))
def test_yaml_indicator_branches_create_parseable_stubs(tmp_path: Path, branch: str) -> None:
    root = write_repository(tmp_path, branch=branch)

    code, result = invoke(root)

    assert code == 0
    metadata = cli.parse_plan_metadata(Path(result["plan_path"]).read_text(encoding="utf-8"))
    assert metadata.branch == branch


def test_yaml_indicator_workflow_updates_remain_parseable(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/workflow")
    code, result = invoke(root)
    assert code == 0
    plan = Path(result["plan_path"])

    code, _ = invoke(root, str(plan), "--workflow", "#review")

    assert code == 0
    assert cli.parse_plan_metadata(plan.read_text(encoding="utf-8")).workflow == "#review"


def test_long_workflow_updates_remain_one_complete_yaml_scalar(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/long-workflow")
    code, result = invoke(root)
    assert code == 0
    plan = Path(result["plan_path"])
    workflow = "review workflow " * 20

    code, _ = invoke(root, str(plan), "--workflow", workflow)

    assert code == 0
    assert cli.parse_plan_metadata(plan.read_text(encoding="utf-8")).workflow == workflow.strip()


def test_one_match_is_reused_but_multiple_matches_fail_without_writing(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/reuse")
    first = _plan(root, "one.md", "feat/reuse")
    code, result = invoke(root)
    assert code == 0
    assert result["plan_path"] == str(first)
    second = _plan(root, "two.md", "feat/reuse")
    before = {path: path.read_bytes() for path in (first, second)}
    code, result = invoke(root)
    assert code == 2
    assert result["error"] == "ambiguous_branch_plans_require_explicit_path"
    assert {path: path.read_bytes() for path in (first, second)} == before


def test_explicit_plan_for_another_branch_is_rejected_without_writing(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/current")
    foreign = _plan(root, "foreign.md", "feat/other")
    before = foreign.read_bytes()

    for arguments in ((str(foreign),), ("--check", str(foreign))):
        code, result = invoke(root, *arguments)

        assert code == 2
        assert result["error"] == "explicit_plan_branch_must_match_active_branch"
        assert foreign.read_bytes() == before


def test_selected_delivery_target_cannot_be_reset_without_a_new_plan(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/delivery-target")
    plan = _plan(root, "selected.md", "feat/delivery-target", target="production", selected=True)
    before = plan.read_bytes()

    code, result = invoke(root, str(plan), "--delivery-target", "on-request")

    assert code == 2
    assert result["error"] == "selected_delivery_target_cannot_be_reset_to_on_request"
    assert plan.read_bytes() == before


def test_selected_delivery_target_can_change_between_staging_and_production(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/delivery-target-change")
    plan = _plan(
        root, "selected.md", "feat/delivery-target-change", target="staging", selected=True
    )

    code, result = invoke(
        root,
        str(plan),
        "--delivery-target",
        "production",
        "--delivery-selected-by-user",
    )
    assert code == 0
    assert result["delivery_target"] == "production"
    assert "delivery_target: production" in plan.read_text(encoding="utf-8")
    assert "delivery_selected_by_user: true" in plan.read_text(encoding="utf-8")

    code, result = invoke(
        root,
        str(plan),
        "--delivery-target",
        "staging",
        "--delivery-selected-by-user",
    )
    assert code == 0
    assert result["delivery_target"] == "staging"
    assert "delivery_target: staging" in plan.read_text(encoding="utf-8")
    assert "delivery_selected_by_user: true" in plan.read_text(encoding="utf-8")


def test_concurrent_no_path_invocations_create_one_plan(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/concurrent")
    environment = {**os.environ, "PYTHONPATH": str(SOURCE_ROOT)}
    command = [sys.executable, "-m", "ollija", "annotate-plan"]
    first = subprocess.Popen(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    second = subprocess.Popen(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    first_out, _ = first.communicate()
    second_out, _ = second.communicate()
    assert first.returncode == second.returncode == 0
    results = [json.loads(first_out), json.loads(second_out)]
    assert len({result["plan_path"] for result in results}) == 1
    assert len(list((root / "docs" / "plans").glob("*.md"))) == 1


def test_check_is_write_free_for_current_stale_missing_and_malformed_inputs(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/check")
    code, created = invoke(root)
    assert code == 0
    path = Path(created["plan_path"])
    current = path.read_bytes()
    before_check = {item.relative_to(root) for item in root.rglob("*")}
    code, result = invoke(root, "--check")
    assert code == 0 and result["result"] == "unchanged"
    assert path.read_bytes() == current
    assert {item.relative_to(root) for item in root.rglob("*")} == before_check

    path.write_text(
        _plan(root, "replacement.md", "feat/check").read_text(encoding="utf-8"), encoding="utf-8"
    )
    stale = path.read_bytes()
    code, result = invoke(root, "--check", str(path))
    assert code == 2 and result["error"] == "plan_annotation_stale_run_annotate_plan"
    assert path.read_bytes() == stale

    missing_root = write_repository(tmp_path / "missing", branch="feat/missing")
    code, result = invoke(missing_root, "--check")
    assert code == 2 and result["error"] == "plan_missing_for_branch"

    malformed = _plan(
        root, "malformed.md", "feat/check", marker="<!-- BEGIN OLLIJA DELIVERY GUIDE -->"
    )
    malformed_before = malformed.read_bytes()
    code, result = invoke(root, "--check", str(malformed))
    assert code == 2 and "marker" in result["error"]
    assert malformed.read_bytes() == malformed_before


@pytest.mark.parametrize("failure", ("fsync", "replace"))
def test_atomic_refresh_preserves_existing_plan_when_write_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root = write_repository(tmp_path, branch="feat/atomic-refresh")
    plan = _plan(root, "existing.md", "feat/atomic-refresh")
    plan.chmod(0o640)
    before = plan.read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError(f"simulated_{failure}_failure")

    monkeypatch.setattr(cli.os, failure, fail)
    code, result = invoke(root, str(plan))

    assert code == 2
    assert result["error"] == f"simulated_{failure}_failure"
    assert plan.read_bytes() == before
    assert plan.stat().st_mode & 0o777 == 0o640
    assert not list(plan.parent.glob(f".{plan.name}.*.tmp"))


def test_failed_initial_fsync_removes_the_uncommitted_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_repository(tmp_path, branch="feat/failed-create")

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("simulated_initial_fsync_failure")

    monkeypatch.setattr(cli.os, "fsync", fail_fsync)
    code, result = invoke(root)

    assert code == 2
    assert result["error"] == "simulated_initial_fsync_failure"
    assert not list((root / "docs" / "plans").glob("*.md"))


def test_git_timeout_is_returned_as_structured_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_repository(tmp_path, branch="feat/git-timeout")

    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(("git", "rev-parse"), 10)

    monkeypatch.setattr("ollija.worktrees.subprocess.run", time_out)
    code, result = invoke(root)

    assert code == 2
    assert result == {"status": "failed", "error": "git_command_timed_out"}


@pytest.mark.parametrize(
    "relative_path", (".ollija/project.yaml", ".ollija/templates/delivery-guide.md")
)
def test_invalid_utf8_tracked_inputs_return_structured_json(
    tmp_path: Path, relative_path: str
) -> None:
    root = write_repository(tmp_path, branch="feat/invalid-utf8")
    (root / relative_path).write_bytes(b"\xff\xfe")

    code, result = invoke(root)

    assert code == 2
    assert result["status"] == "failed"
    assert result["error"].startswith("could not read ")


def test_explicit_escape_detached_head_and_unselected_autonomous_target_do_not_write(
    tmp_path: Path,
) -> None:
    root = write_repository(tmp_path, branch="feat/safe")
    outside = root.parent / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    code, result = invoke(root, str(outside))
    assert code == 2 and result["error"] == "explicit_plan_path_must_be_under_active_plan_directory"
    assert not (root / "docs" / "plans").exists()

    code, result = invoke(root, "--delivery-target", "production")
    assert code == 2 and result["error"] == "delivery_target_requires_explicit_user_selection"
    assert not (root / "docs" / "plans").exists()

    code, result = invoke(
        root,
        "--workflow",
        "lfg",
        "--delivery-target",
        "production",
        "--delivery-selected-by-user",
    )
    assert code == 0 and result["delivery_target"] == "production"
    created = Path(result["plan_path"]).read_text(encoding="utf-8")
    assert "workflow: lfg" in created
    assert "delivery_target: production" in created
    assert "delivery_selected_by_user: true" in created

    _git(root, "checkout", "--detach")
    code, result = invoke(root)
    assert code == 2 and result["error"] == "detached_head_requires_named_branch"


def test_trusted_project_root_supplies_config_for_an_active_linked_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = write_repository(tmp_path, branch="primary-trusted-config")
    linked = tmp_path / "linked-worktree"
    _git(primary, "worktree", "add", "-b", "feat/trusted-config", str(linked))
    assert not (linked / ".ollija" / "project.yaml").exists()

    monkeypatch.setenv("OLLIJA_PROJECT_ROOT", str(primary))
    monkeypatch.setenv("OLLIJA_WORKTREE_CWD", str(linked))
    code, result = invoke(linked)

    assert code == 0
    assert result["authoritative_root"] == str(primary)
    assert result["active_worktree"] == str(linked)
    assert Path(result["plan_path"]).is_relative_to(linked / "docs" / "plans")


def test_hook_mode_lock_contention_returns_promptly(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/hook-lock")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import fcntl, sys; "
                "stream = open(sys.argv[1]); "
                "fcntl.flock(stream.fileno(), fcntl.LOCK_EX); "
                "print('locked', flush=True); "
                "sys.stdin.read()"
            ),
            str(root / ".git" / "HEAD"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdin is not None
    assert holder.stdout.readline().strip() == "locked"
    try:
        environment = {
            **os.environ,
            "PYTHONPATH": str(SOURCE_ROOT),
            "OLLIJA_HOOK_NONBLOCKING_LOCK": "1",
        }
        completed = subprocess.run(
            [sys.executable, "-m", "ollija", "annotate-plan"],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=1,
        )
    finally:
        holder.stdin.close()
        holder.wait(timeout=1)

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["error"] == "annotation_lock_busy_rerun_annotate_plan"
