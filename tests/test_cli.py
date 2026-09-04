from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import write_repository

from ollija.cli import build_parser

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_help_exposes_only_the_supported_commands() -> None:
    help_text = build_parser().format_help()

    assert "init" in help_text
    assert "annotate-plan" in help_text
    for retired in ("status", "doctor", "go", "stop", "stage", "release", "worktree"):
        assert retired not in help_text


def test_wrapper_and_python_module_reach_the_same_command(tmp_path: Path) -> None:
    root = write_repository(tmp_path, branch="feat/wrapper")
    environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    wrapper = subprocess.run(
        [str(Path(sys.executable).parent / "ollija"), "annotate-plan"],
        cwd=root,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    module = subprocess.run(
        [sys.executable, "-m", "ollija", "annotate-plan"],
        cwd=root,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert wrapper.returncode == module.returncode == 0
    assert json.loads(wrapper.stdout)["plan_path"] == json.loads(module.stdout)["plan_path"]
    assert json.loads(module.stdout)["result"] == "unchanged"
