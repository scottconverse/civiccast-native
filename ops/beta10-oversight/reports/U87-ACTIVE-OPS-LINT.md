# U87 active-ops lint receipt

Candidate checked: branch `codex/u73-caption-measurements`, HEAD `d258e46d`.
This receipt records active-ops cleanup, including the credential/security follow-up below;
it is not a full-repository lint, format, type or operational pass. Root separately owns
the exact historical U37 instrument discovery exclusion; no active-ops path is excluded.

## Historical mechanical cleanup

The initial pass changed nine active-ops paths. This follow-up added mechanical
edits in two further paths, so the combined set of eleven source paths touched
by the two local passes is:

- `ops/beta10-oversight/bin/changeover_hole_watch.py`
- `ops/beta10-oversight/bin/loudness_window_adjudicate.py`
- `ops/beta10-oversight/bin/monitors/mkjob.py`
- `ops/beta10-oversight/bin/release/pdl.py`
- `ops/beta10-oversight/bin/release/unz.py`
- `ops/beta10-oversight/bin/rung_check.py`
- `ops/beta10-oversight/bin/test_loudness_window_adjudicate.py`
- `ops/beta10-oversight/bin/test_rung_check_caption.py`
- `ops/docs-sprint/tools/build_manual.py`
- `ops/docs-sprint/tools/gen_cli_inventory.py`
- `ops/docs-sprint/tools/gen_env_inventory.py`

Edits were limited to selected import/format cleanup and the low-risk Ruff rules
F841, PTH105/118/123/208, RUF007/046/059, SIM105/108/115, and UP017/031. Path
composition retained strings at subprocess/JSON boundaries; file modes,
encodings, exception scopes, and numeric output precision were preserved. No
historical `.agent-runs`
evidence instrument was changed. The other pre-existing dirty files were
preserved.

Commands and raw summaries:

```text
gh run view 37225882300 --log-failed
Found 108 errors.
[*] 33 fixable with the `--fix` option (13 hidden fixes can be enabled with the `--unsafe-fixes` option).
##[error]Process completed with exit code 1.

uv run ruff check --fix --select F401,E401,I001,RUF100 ops/beta10-oversight/bin ops/docs-sprint/tools
uv run ruff format ops/beta10-oversight/bin/changeover_hole_watch.py ops/beta10-oversight/bin/monitors/mkjob.py ops/beta10-oversight/bin/release/pdl.py ops/beta10-oversight/bin/release/unz.py

uv run pytest ops/beta10-oversight/bin/test_loudness_window_adjudicate.py -q
......................                                                   [100%]
22 passed in 1.03s

uv run ruff format --check ops/beta10-oversight/bin/changeover_hole_watch.py ops/beta10-oversight/bin/monitors/mkjob.py ops/beta10-oversight/bin/release/pdl.py ops/beta10-oversight/bin/release/unz.py
4 files already formatted

uv run ruff check --select F401,E401,I001,RUF100 ops/beta10-oversight/bin ops/docs-sprint/tools
All checks passed!

uv run --offline ruff check --select F841,PTH105,PTH118,PTH123,PTH208,RUF007,RUF046,RUF059,SIM105,SIM108,SIM115,UP017,UP031 ops/beta10-oversight/bin ops/docs-sprint/tools
All checks passed!

uv run --offline python -m compileall -q ops/beta10-oversight/bin/changeover_hole_watch.py ops/beta10-oversight/bin/loudness_window_adjudicate.py ops/beta10-oversight/bin/monitors/mkjob.py ops/beta10-oversight/bin/release/pdl.py ops/beta10-oversight/bin/release/unz.py ops/beta10-oversight/bin/rung_check.py ops/beta10-oversight/bin/test_loudness_window_adjudicate.py ops/beta10-oversight/bin/test_rung_check_caption.py ops/docs-sprint/tools/gen_cli_inventory.py ops/docs-sprint/tools/gen_env_inventory.py
exit 0 (no output)

uv run --offline pytest ops/beta10-oversight/bin/test_loudness_window_adjudicate.py ops/beta10-oversight/bin/test_rung_check_air_audio.py ops/beta10-oversight/bin/test_rung_check_caption.py -q [first attempt]
2 failed, 35 passed in 12.60s
Both failures were NameError: a_t not defined in loud_part_correlate after an overbroad RUF059 cleanup discarded a value used for air_from_s. The test caught it; a_t was restored in that function, while the genuinely unused value in correlate remains discarded.

uv run --offline pytest ops/beta10-oversight/bin/test_loudness_window_adjudicate.py ops/beta10-oversight/bin/test_rung_check_air_audio.py ops/beta10-oversight/bin/test_rung_check_caption.py -q [corrected rerun]
37 passed in 12.16s

uv run ruff check --output-format=json ops/beta10-oversight/bin ops/docs-sprint/tools [before the follow-up pass]
61 remaining ops findings (see pre-follow-up inventory below).

uv run ruff check --output-format=json ops/beta10-oversight/bin ops/docs-sprint/tools [after the follow-up pass, before u86 handoff]
16 remaining ops findings: B905 (1), E402 (2), S310 (2), S311 (1), S603 (7), S607 (2), UP024 (1).
```

The latest CI log still contains 16 findings in the retained U37
`.agent-runs/native-windows/beta10-u37-mux-video-stall/evidence/instruments`
and 92 ops findings. Thirty-one safe mechanical ops findings were cleared
locally in the first pass. The follow-up cleared 44 additional targeted
mechanical findings plus the watcher adjacent-pair B905 by using `pairwise`,
leaving 16 ops findings at the time of handoff. The
historical 16 are not proposed for cleanup or exclusion here.

## Pre-follow-up inventory: 61 ops findings

"Mechanical suggestion" below means likely style/API modernization with
behavior-preserving intent, but should still be reviewed in context before
batch fixing. "Correctness/security review" identifies findings whose behavior,
input, or trust assumptions need explicit judgment before changing anything.

| Rule | Count | File(s) and per-file count | Classification |
|---|---:|---|---|
| B905 | 2 | `changeover_hole_watch.py` (1); `loudness_window_adjudicate.py` (1) | Correctness review: `zip` truncation/length invariant; `strict=` or pairing intent must be chosen deliberately. |
| E402 | 2 | `test_loudness_window_adjudicate.py` (2) | Correctness/test-structure review: imports are deliberately located beside later tests; moving them can change setup semantics. |
| F841 | 1 | `release/pdl.py` (1) | Mechanical suggestion: unused exception binding can be removed without changing catch behavior. |
| PTH105 | 3 | `loudness_window_adjudicate.py` (2); `rung_check.py` (1) | Mechanical suggestion: `os.replace` to `Path.replace`; preserve atomic replacement semantics. |
| PTH118 | 11 | `changeover_hole_watch.py` (8); `monitors/mkjob.py` (3) | Mechanical suggestion: `os.path.join` to `Path` composition; check string/path boundary where passed to subprocess/environment. |
| PTH123 | 9 | `changeover_hole_watch.py` (3); `monitors/mkjob.py` (2); `release/pdl.py` (2); `rung_check.py` (1); `gen_cli_inventory.py` (1) | Mechanical suggestion: `open` to `Path.open`; retain encoding/newline/mode behavior. |
| PTH208 | 2 | `changeover_hole_watch.py` (2) | Mechanical suggestion with behavior review: `os.listdir` to `Path.iterdir`; preserve filtering and ordering assumptions. |
| RUF007 | 1 | `changeover_hole_watch.py` (1) | Mechanical suggestion: `zip` successive items to `itertools.pairwise`, after confirming same adjacent-pair behavior. |
| RUF046 | 1 | `loudness_window_adjudicate.py` (1) | Mechanical suggestion: redundant `int` cast; confirm the value is already an `int` on all input paths. |
| RUF059 | 3 | `loudness_window_adjudicate.py` (3) | Mechanical suggestion: remove unused unpacked names or use `_`; inspect tuple shape only if changing the unpack. |
| S310 | 2 | `release/pdl.py` (2) | Security review: `urlopen` scheme allowlist and the source/trust of the refreshed download URL. |
| S311 | 1 | `test_loudness_window_adjudicate.py` (1) | Test-only false-positive candidate: seeded `random.Random` creates deterministic fixtures; not a production cryptographic use. Preserve reproducibility; suppression may be more accurate than switching RNG. |
| S603 | 7 | `changeover_hole_watch.py` (1); `loudness_window_adjudicate.py` (1); `release/pdl.py` (1); `rung_check.py` (1); `test_rung_check_air_audio.py` (1); `test_rung_check_caption.py` (1); `build_manual.py` (1) | Security review: verify executable/argv provenance and shell usage per call. Ruff's warning alone does not establish a vulnerability. |
| S607 | 2 | `release/pdl.py` (2) | Security review: partial executable names rely on PATH resolution; establish expected trusted executable lookup. |
| SIM105 | 3 | `loudness_window_adjudicate.py` (1); `rung_check.py` (1); `gen_env_inventory.py` (1) | Mechanical suggestion with error-policy review: `contextlib.suppress(OSError)` preserves intentional swallow only if exception scope stays identical. |
| SIM108 | 1 | `changeover_hole_watch.py` (1) | Mechanical suggestion: equivalent conditional expression, confirm readability. |
| SIM115 | 2 | `monitors/mkjob.py` (1); `rung_check.py` (1) | Mechanical/resource-lifecycle suggestion: context manager; verify lifetime stays within same scope. |
| UP017 | 4 | `loudness_window_adjudicate.py` (1); `rung_check.py` (1); `test_loudness_window_adjudicate.py` (1); `test_rung_check_caption.py` (1) | Mechanical suggestion if the supported Python baseline provides `datetime.UTC`; current project runtime is expected to be checked before applying. |
| UP024 | 1 | `release/pdl.py` (1) | Correctness/compatibility review: exception alias consolidation can alter which errors are caught or attributes available. |
| UP031 | 3 | `release/pdl.py` (2); `release/unz.py` (1) | Mechanical formatting suggestion with output check: percent formatting to f-strings; preserve displayed text and numeric formatting. |
| **Total** | **61** | 12 files | **Historical inventory before the mechanical follow-up and separate security fixes.** |

## Historical remainder at mechanical-pass handoff: 16 ops findings

These remain outside this worker's approved low-risk set and were handed to
u86 for the separately authorized correctness/security review. No one should
infer an overall lint pass from the selected-rule check above.

| Rule | Count | File(s) and per-file count | Classification |
|---|---:|---|---|
| B905 | 1 | `loudness_window_adjudicate.py` (1) | Correctness review: zip length/pairing invariant. The watcher's adjacent-pair scan now uses `pairwise`. |
| E402 | 2 | `test_loudness_window_adjudicate.py` (2) | Test setup/import-order review; moved/relocated by separate review if safe. |
| S310 | 2 | `release/pdl.py` (2) | Security review of permitted URL schemes and refreshed download URL. |
| S311 | 1 | `test_loudness_window_adjudicate.py` (1) | Deterministic test RNG; likely narrow documented suppression, not a crypto RNG substitution. |
| S603 | 7 | `changeover_hole_watch.py` (1); `loudness_window_adjudicate.py` (1); `release/pdl.py` (1); `rung_check.py` (1); `test_rung_check_air_audio.py` (1); `test_rung_check_caption.py` (1); `build_manual.py` (1) | Per-call subprocess provenance review; warning is not by itself a vulnerability. |
| S607 | 2 | `release/pdl.py` (2) | Security review of PATH-resolved executables. |
| UP024 | 1 | `release/pdl.py` (1) | Compatibility/error-catching behavior review; not in the approved mechanical set. |
| **Total** | **16** | **8 files** | **Inventory before u86's separate review/fixes; refresh against the integrated candidate.** |

## Invocation / retention evidence

Command used to look for operational invocation sites:

```text
rg -n --glob '*.yml' --glob '*.yaml' --glob '*.ps1' --glob '*.sh' --glob '*.toml' '(changeover_hole_watch|loudness_window_adjudicate|mkjob\.py|release[/\\](pdl|unz)\.py|rung_check\.py|test_loudness_window_adjudicate|test_rung_check_air_audio|test_rung_check_caption|build_manual\.py|gen_cli_inventory\.py|gen_env_inventory\.py)' .github ops scripts pyproject.toml
```

Observed from that search and the source references:

- `rung_check.py` is operationally invoked by `ops/beta10-oversight/bin/rung.ps1`;
  it loads the loudness adjudicator in its corresponding mode. Their findings
  affect active oversight checks, not station product runtime.
- The three `test_*.py` files are invoked by the local `audit-u66.ps1` helper;
  no GitHub Actions workflow invocation was found in `.github/workflows`.
- `changeover_hole_watch.py` and `mkjob.py` have documented/manual oversight
  use, but no active CI workflow invocation was found. The `mkjob.py` call is
  described in the dated handoff; the watch script appears in oversight
  instructions/log history.
- `release/pdl.py` and `release/unz.py` have no invocation reference in the
  searched active workflow/script/config paths. They are retained; this task fixes
  their active lint surface and does not request deletion or an archival decision.
- `build_manual.py` has a documented manual docs-sprint invocation; no CI
  workflow invocation was found. The two `gen_*_inventory.py` scripts are
  documented generators for checked-in inventory outputs; no CI invocation
  was found.
- The GitHub Actions workflow invokes repository-wide Ruff. Root's current exact
  discovery exclusion removes only the twelve retained U37 evidence instruments;
  all active product/test/tool paths remain eligible. Discovery is not execution.

The mechanical passes changed source as listed above. They made no historical-artifact
edits, extra test framework/harness, commits or pushes. Current nonmechanical fixes follow.

## Current integrated active-ops result

After the mechanical worker released shared files, the security reviewer changed eight
active paths: pdl, watcher, loudness adjudicator, rung checker, three existing ops test modules,
and the manual builder. The combined mechanical/security set is twelve paths (the earlier
eleven plus test_rung_check_air_audio.py). No archived instrument bytes were edited.

The actual credential exposure was corrected, not suppressed: pdl formerly placed the token
returned by gh auth token in curl argv. It now resolves local operator gh/curl executables,
sends the Authorization header only on stdin through curl -H @-, disables curlrc traces,
keeps the fixed GitHub artifact API workflow and validates an ASCII numeric artifact ID.
The initial signed download URL and every urllib redirect require HTTPS without userinfo;
HTTP/file downgrades are rejected. Authenticated subprocess failures produce generic messages
without captured stdout/stderr or chained exception text. No credential is written to a
header file. This does not claim protection against a compromised operator tool/PATH or
privileged process-memory reader. Header stdin support is documented by the
[official curl manual](https://curl.se/docs/manpage.html#-H).

Remaining S603 suppressions are per-call, documented local operator/test contracts:
watcher uses fixed installed ffprobe; adjudicator uses operator-selected local ffmpeg from
--ffmpeg or local receipt; rung uses current Python and sibling adjudicator; tests use current
Python plus owned/explicit test tool; manual builder uses local node/mermaid installation and
generated paths. These are not assertions that shell=False alone authenticates an executable.
The deterministic seeded audio fixture remains seeded (S311); datetime/random imports moved
to the standard-library import block without changing setup. Pearson uses strict zip because
its sole production caller passes complete equal-length slices; watcher uses adjacent pairwise.
IOError is the OSError alias on the supported Python3.12 baseline.

Personally executed baseline existing loudness suite: `22 passed in 1.04s`. Credential
sensitivity RED used AST-extracted production fresh_url with fake subprocess and a synthetic
token: `AssertionError: credential entered process argv`, exit1. No helper module import,
real credential read, subprocess or download occurred. The same extracted production path
then passed assertions for stdin-only token, unchanged signed URL, fixed API argv, curlrc
disabled, invalid initial schemes/userinfo, HTTPS redirect positive and downgrade negatives,
and generic authentication/curl nonzero/exception failures with synthetic captured secret text.
GREEN output: `PASS: extracted production functions; stdin-only credential, fixed API, HTTPS initial/redirect guards, generic subprocess failures; no process/auth/network`.

Final commands (existing release interpreter, no installation):

```text
python.exe -m ruff check ops/beta10-oversight/bin ops/docs-sprint/tools
All checks passed!

python.exe -c "import os; os.environ.pop('CIVICCAST_STAFF_TOKENS',None); import pytest; raise SystemExit(pytest.main(['-q','ops/beta10-oversight/bin/test_loudness_window_adjudicate.py','ops/beta10-oversight/bin/test_rung_check_air_audio.py','ops/beta10-oversight/bin/test_rung_check_caption.py']))"
37 passed in 11.91s

python.exe -m ruff format --check ops/beta10-oversight/bin ops/docs-sprint/tools
7 files would be reformatted, 11 files already formatted
```

At this intermediate checkpoint, format was non-green for changeover_hole_watch.py, loudness_window_adjudicate.py,
rung_check.py, three ops test modules and untouched publish_beta10_waived.py. No broad whole-file
format churn was applied by this review. git diff --check passed. Root must account for this
format gate and product typing separately; no overall CI-ready claim is made here.

Independent review of root's narrow archive config: complete evidence README identifies
commit-bound historical measurements and retained reproduction code; U37 report cites those
same instruments; sdist already excludes .agent-runs. No operational reference was found in
executable .github/scripts/ops configs. Archive diff is empty. Discovery comparison using
isolated original exclusions versus current config reproduced1643 to1631: exactly twelve U37
instrument files removed, no additions/active path removals. No blanket .agent-runs exclusion.

proved: active-ops Ruff green,37 existing tests green; extracted credential check assertion RED
then GREEN including redirect/failure negatives; historical bytes unchanged; lane: Critical

### Final bounded subprocess and format checkpoint

Root requested bounded gh/curl waits. Extracted-function RED before the change:
`AssertionError: auth lookup has no bounded wait`, exit1. Auth now has30s and the
authenticated redirect request120s; TimeoutExpired is covered by the same generic redaction
policy. Credential/scheme/error/timeout fake checks now reside only as this owned evidence
check, not a repository harness or operational downloader execution:

`C:/Users/scott/Documents/Codex/2026-09-16/re/civiccast-ds-oversight/evidence/u87-caption-recovery/ops-pdl-security-extracted-check.py`

Exact command: existing release Python interpreter followed by that absolute evidence path.
Final output: `PASS: stdin-only credential; 30s auth/120s redirect; HTTPS initial/redirect guards; auth/curl failure+timeout redaction; no process/auth/network`, exit0.
The check executes only AST-selected imports/functions/classes with synthetic subprocess and
tool providers. It never imports pdl's top-level body, fetches credentials or opens a network.
Final pdl SHA256: D1C5B26B6B8FFCDFF92EB9A170952906F4F8A277E093B79ED79DAEC85B215AB1.

Root separately formatted the exact seven listed files, checking before/after AST equality
and never importing/executing side-effectful helpers. The earlier format failure is a historical
checkpoint, now superseded: independently reran scoped Ruff `All checks passed!`, scoped
format `18 files already formatted`, and diff-check clean. Root independently reran the same
three existing test modules: `37 passed in 11.73s` (root evidence, distinct from my11.91s run).
No full-repository formatter/exclusion, commit, push or operational run is claimed.
