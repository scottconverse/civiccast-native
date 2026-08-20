from pathlib import Path


def test_cleanroom_runner_injects_git_ownership_and_identity_via_env() -> None:
    """Audit item #27 / Cleanroom root cause: on the GitHub-hosted runner the
    checkout is owned by uid 1001 while the cleanroom container runs as
    root, so git >= 2.35's safe.directory check refused both the
    bind-mounted repo (the banner's suppressed "no-git") and the copied
    tree — and the snapshot fallback's per-repo `git config` writes died
    against a repo git refused to see ("fatal: not in a git directory").
    The fix must be environment-level (GIT_CONFIG_COUNT injection) so it
    covers every git call in the script AND child processes (pytest's
    source-state collectors shell out to git), with no config-file writes.
    """

    script = Path("docker/run-cleanroom.sh").read_text(encoding="utf-8")

    assert "GIT_CONFIG_COUNT=3" in script
    assert "GIT_CONFIG_KEY_0=safe.directory" in script
    assert "GIT_CONFIG_VALUE_0='*'" in script
    assert "GIT_CONFIG_KEY_1=user.email" in script
    assert "GIT_CONFIG_KEY_2=user.name" in script
    # The env export must precede the first git use (the banner probe).
    assert script.index("GIT_CONFIG_COUNT=3") < script.index('git -C "$REPO_DIR" rev-parse')
    # The fragile per-repo config writes must stay gone from the fallback.
    assert "git config user.email" not in script
    assert "git config user.name" not in script


def test_cleanroom_runner_rebuilds_broken_copied_git_metadata() -> None:
    script = Path("docker/run-cleanroom.sh").read_text(encoding="utf-8")

    assert 'cd "$WORK_DIR"' in script
    assert "git rev-parse --is-inside-work-tree" in script
    assert "git init --quiet" in script
    assert 'git commit --quiet -m "cleanroom source snapshot"' in script
    assert script.index("git rev-parse --is-inside-work-tree") > script.index('cd "$WORK_DIR"')
    assert script.index("git rev-parse --is-inside-work-tree") < script.index(
        "# Strip CR from text files."
    )


def test_cleanroom_runner_fails_loudly_on_an_empty_bind_mount() -> None:
    """Defense-in-depth for direct `make cleanroom` runs: an empty/absent
    bind mount must fail immediately with the mount named, before any
    tooling produces a cryptic downstream error."""

    script = Path("docker/run-cleanroom.sh").read_text(encoding="utf-8")

    assert "if [ ! -f pyproject.toml ]; then" in script
    copy_index = script.index('cp -a "$REPO_DIR/." "$WORK_DIR/"')
    guard_index = script.index("if [ ! -f pyproject.toml ]; then")
    git_fallback_index = script.index("git rev-parse --is-inside-work-tree")
    assert copy_index < guard_index < git_fallback_index


def test_cleanroom_workflow_probes_the_bind_mount_before_the_full_gate() -> None:
    """The workflow pre-flights the mount with a cheap busybox probe (with
    retries) so an empty mount source fails in seconds, not after the
    7-10 minute gate build. Kept alongside the git-ownership fix — they
    guard different failure modes (missing source vs refused repo)."""

    workflow = Path(".github/workflows/ci-cleanroom-e2e.yml").read_text(encoding="utf-8")

    assert "test -f /probe/pyproject.toml" in workflow
    assert "mount_ok=false" in workflow
    assert 'if [ "$mount_ok" != true ]; then' in workflow
    # The stale self-hosted/WSL2 runner story must stay corrected: this is
    # a GitHub-hosted runner and the docs must not send the next debugging
    # session down the Docker Desktop rabbit hole again.
    assert "runs-on: ubuntu-latest" in workflow
    assert "WSL Integration" not in workflow
    assert "docker/for-win" not in workflow
    assert "GitHub-hosted runner" in workflow
    preflight_index = workflow.index("test -f /probe/pyproject.toml")
    real_run_index = workflow.index("target=/work/civiccast")
    assert preflight_index < real_run_index
