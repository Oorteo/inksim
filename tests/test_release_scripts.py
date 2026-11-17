# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_project(tmp_path: Path) -> tuple[Path, str]:
    project = tmp_path / "project"
    (project / "scripts" / "release").mkdir(parents=True)
    (project / "scripts" / "pypi").mkdir(parents=True)
    for relative_path in (
        "scripts/release/010_pre_release.sh",
        "scripts/release/030_final_release.sh",
        "scripts/pypi/030_send_pypi.sh",
    ):
        destination = project / relative_path
        shutil.copy2(ROOT / relative_path, destination)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "inksim"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )

    _git(project, "init", "--quiet", "--initial-branch", "main")
    _git(project, "config", "user.name", "Release Script Test")
    _git(project, "config", "user.email", "release-test@example.invalid")
    _git(project, "add", "pyproject.toml")
    _git(project, "commit", "--quiet", "-m", "Initial commit")
    main_commit = _git(project, "rev-parse", "HEAD")
    _git(project, "update-ref", "refs/remotes/origin/main", main_commit)
    _git(project, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return project, main_commit


def _fake_tools(tmp_path: Path, *, include_twine: bool = False) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\nprintf '%s\\n' '1.2.3'\n", encoding="utf-8")
    uv.chmod(0o755)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "repo" ]; then\n'
        "  printf '%s\\n' 'Oorteo/inksim'\n"
        "else\n"
        "  printf '%s\\n' '{\"check_runs\":[]}'\n"
        "fi\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    if include_twine:
        twine = bin_dir / "twine"
        twine.write_text(
            '#!/bin/sh\nprintf "called" > "$TWINE_MARKER"\n',
            encoding="utf-8",
        )
        twine.chmod(0o755)
        env["TWINE_MARKER"] = str(tmp_path / "twine-called")
    return env


def _run_script(
    project: Path,
    script: str,
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(project / script), *args],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )


def test_pre_release_refuses_a_second_tag_on_the_same_commit(tmp_path):
    project, _ = _create_project(tmp_path)
    env = _fake_tools(tmp_path)

    first = _run_script(
        project,
        "scripts/release/010_pre_release.sh",
        env,
        "--no-fetch",
        "--no-push",
        "--yes",
    )
    assert first.returncode == 0, first.stderr
    assert _git(project, "tag", "--points-at", "HEAD") == "v1.2.3-rc.1"

    second = _run_script(
        project,
        "scripts/release/010_pre_release.sh",
        env,
        "--no-fetch",
        "--no-push",
        "--yes",
    )
    assert second.returncode != 0
    assert "already has release tag(s)" in second.stderr
    assert _git(project, "tag", "--list", "v1.2.3-rc.*") == "v1.2.3-rc.1"

    _git(project, "commit", "--quiet", "--allow-empty", "-m", "Next candidate")
    next_candidate = _run_script(
        project,
        "scripts/release/010_pre_release.sh",
        env,
        "--no-fetch",
        "--no-push",
        "--yes",
    )
    assert next_candidate.returncode == 0, next_candidate.stderr
    assert _git(project, "tag", "--points-at", "HEAD") == "v1.2.3-rc.2"


def test_final_release_defaults_to_main_but_allows_explicit_branch(tmp_path):
    project, main_commit = _create_project(tmp_path)
    _git(project, "switch", "--quiet", "-c", "feature")
    (project / "feature.txt").write_text("test branch\n", encoding="utf-8")
    _git(project, "add", "feature.txt")
    _git(project, "commit", "--quiet", "-m", "Feature commit")
    feature_commit = _git(project, "rev-parse", "HEAD")

    env = _fake_tools(tmp_path)
    script = "scripts/release/030_final_release.sh"
    default_target = _run_script(
        project,
        script,
        env,
        "--dry-run",
        "--no-fetch",
        "--no-require-green",
    )
    assert default_target.returncode == 0, default_target.stderr
    assert "Branch:       main" in default_target.stdout
    assert main_commit[:12] in default_target.stdout

    explicit_target = _run_script(
        project,
        script,
        env,
        "--branch",
        "feature",
        "--dry-run",
        "--no-fetch",
        "--no-require-green",
    )
    assert explicit_target.returncode == 0, explicit_target.stderr
    assert "Branch:       feature (checked out)" in explicit_target.stdout
    assert feature_commit[:12] in explicit_target.stdout


def test_final_release_refuses_a_second_release_tag_on_the_commit(tmp_path):
    project, _ = _create_project(tmp_path)
    _git(project, "tag", "-a", "v1.2.3-rc.1", "-m", "v1.2.3-rc.1")

    result = _run_script(
        project,
        "scripts/release/030_final_release.sh",
        _fake_tools(tmp_path),
        "--dry-run",
        "--no-fetch",
        "--no-require-green",
    )

    assert result.returncode != 0
    assert "already has release tag(s): v1.2.3-rc.1" in result.stderr


def test_pypi_upload_requires_default_branch_unless_explicitly_overridden(tmp_path):
    project, _ = _create_project(tmp_path)
    _git(project, "switch", "--quiet", "-c", "feature")
    (project / "feature.txt").write_text("test branch\n", encoding="utf-8")
    _git(project, "add", "feature.txt")
    _git(project, "commit", "--quiet", "-m", "Feature commit")
    _git(project, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    dist = project / "dist"
    dist.mkdir()
    (dist / "inksim-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "inksim-1.2.3.tar.gz").write_bytes(b"source")
    env = _fake_tools(tmp_path, include_twine=True)
    script = "scripts/pypi/030_send_pypi.sh"

    rejected = _run_script(project, script, env, "--yes")
    assert rejected.returncode != 0
    assert "restricted to commits reachable from origin/main" in rejected.stderr
    assert not Path(env["TWINE_MARKER"]).exists()

    overridden = _run_script(project, script, env, "--allow-non-main", "--yes")
    assert overridden.returncode == 0, overridden.stderr
    assert "bypasses the main-branch check" in overridden.stderr
    assert Path(env["TWINE_MARKER"]).read_text(encoding="utf-8") == "called"
