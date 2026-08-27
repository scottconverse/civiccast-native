# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Provision CivicCast's reviewed native-Windows server and media dependencies.

The committed lock is the acquisition allowlist. Every downloaded archive is
size- and SHA-256-verified before cache admission, extracted without links or
path traversal, and staged transactionally with a bidirectional file manifest.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
LOCK_PATH: Final[Path] = ROOT / "native-windows-runtime-dependencies.lock.json"
DEFAULT_CACHE: Final[Path] = ROOT / "build" / "native-runtime-dependency-cache"
DEFAULT_OUTPUT: Final[Path] = ROOT / "build" / "native-runtime-dependencies"
MANIFEST_NAME: Final[str] = "native-runtime-dependencies-manifest.json"
#: Optional persistent, hash-addressed archive mirror. When set (or passed as
#: ``fetch_locked_artifact``'s ``mirror=``), verified archives are read from
#: and written back to ``<mirror>/<sha256>/<filename>`` -- a survival layer
#: for upstream release assets that can vanish (BtbN/FFmpeg-Builds prunes
#: daily autobuild tags; candidate run 33094460301 died on a 404 of the
#: then-pinned asset). The committed lock's size+SHA-256 pin stays the sole
#: admission authority: a mirror entry is verified exactly like a fresh
#: download before it is used, and ignored (then repaired) if it does not
#: match.
MIRROR_ENV_VAR: Final[str] = "CIVICCAST_RUNTIME_ARTIFACT_MIRROR"
SHA256SUMS_NAME: Final[str] = "SHA256SUMS"
LICENSE_BOM_NAME: Final[str] = "LICENSE-BOM.md"
_TRUST_ARTIFACTS: Final[frozenset[str]] = frozenset(
    {MANIFEST_NAME, SHA256SUMS_NAME, LICENSE_BOM_NAME}
)

_CHUNK_BYTES: Final[int] = 1024 * 1024
_ARTIFACT_NAMES: Final[frozenset[str]] = frozenset(
    {"postgres", "tsduck", "ffmpeg", "node", "ollama"}
)
_OUTPUT_ROOTS: Final[dict[str, str]] = {
    "postgres": "postgresql",
    "tsduck": "tsduck",
    "ffmpeg": "ffmpeg",
    "node": "node",
    "ollama": "ollama",
}
_ALLOWED_SPDX_LICENSES: Final[frozenset[str]] = frozenset(
    {
        "Apache-2.0",
        "BSD-2-Clause",
        "LGPL-3.0-or-later",
        "MIT",
        "PostgreSQL",
    }
)
_DOWNLOAD_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "get.enterprisedb.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "nodejs.org",
        "raw.githubusercontent.com",
    }
)
_SPDX_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9.-]+")
_WINDOWS_FORBIDDEN_CHARS: Final[frozenset[str]] = frozenset('<>:"|?*')
_WINDOWS_RESERVED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)


class RuntimeDependencyProvisionError(RuntimeError):
    """The reviewed runtime dependency closure could not be reconstructed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_download_url(value: object) -> urllib.parse.ParseResult:
    if not isinstance(value, str):
        raise RuntimeDependencyProvisionError("artifact URL must be a string")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https":
        raise RuntimeDependencyProvisionError(f"artifact URL must use HTTPS: {value}")
    if parsed.hostname not in _DOWNLOAD_HOSTS:
        raise RuntimeDependencyProvisionError(f"artifact URL host is not approved: {value}")
    if parsed.username or parsed.password or parsed.fragment:
        raise RuntimeDependencyProvisionError(f"artifact URL contains forbidden fields: {value}")
    return parsed


def is_approved_download_url(value: object) -> bool:
    """Return whether a URL satisfies the reviewed acquisition boundary."""

    try:
        _validated_download_url(value)
    except RuntimeDependencyProvisionError:
        return False
    return True


def _safe_relative_path(value: object, *, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise RuntimeDependencyProvisionError(f"artifact {field} must be non-empty")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or path.parts[0].endswith(":")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RuntimeDependencyProvisionError(f"artifact {field} is unsafe: {value}")
    return path


def validate_lock(lock: Mapping[str, Any]) -> None:
    """Refuse incomplete, malformed, or unreviewable dependency metadata."""

    if lock.get("schema_version") != 2:
        raise RuntimeDependencyProvisionError("unsupported runtime dependency lock schema")
    if lock.get("target") != "windows-x86_64":
        raise RuntimeDependencyProvisionError(
            "runtime dependency lock target must be windows-x86_64"
        )
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != _ARTIFACT_NAMES:
        raise RuntimeDependencyProvisionError(
            "runtime dependency lock has an incomplete artifact set"
        )

    required_fields = {
        "archive",
        "bytes",
        "expected_executables",
        "filename",
        "sha256",
        "spdx_license",
        "strip_prefix",
        "url",
        "version",
    }
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            raise RuntimeDependencyProvisionError(f"{name} artifact must be an object")
        allowed_fields = (
            required_fields
            | ({"include"} if name in {"postgres", "node"} else set())
            | ({"license_notice"} if name == "ollama" else set())
        )
        # ``fallback_urls`` is the one OPTIONAL field: a reviewed, ordered
        # list of alternate download URLs for the same exact bytes, tried
        # only after the primary URL fails. Same host allowlist, same
        # size+SHA-256 verification -- a fallback can change where the bytes
        # come from, never which bytes are accepted.
        if set(artifact) - {"fallback_urls"} != allowed_fields:
            raise RuntimeDependencyProvisionError(
                f"{name} artifact fields differ from the reviewed schema"
            )
        _validated_download_url(artifact["url"])
        if "fallback_urls" in artifact:
            fallback_urls = artifact["fallback_urls"]
            if (
                not isinstance(fallback_urls, list)
                or not fallback_urls
                or any(not isinstance(item, str) for item in fallback_urls)
            ):
                raise RuntimeDependencyProvisionError(
                    f"{name} artifact fallback_urls must be a non-empty list of URLs"
                )
            for item in fallback_urls:
                _validated_download_url(item)
            if len({artifact["url"], *fallback_urls}) != len(fallback_urls) + 1:
                raise RuntimeDependencyProvisionError(
                    f"{name} artifact fallback_urls contain duplicates"
                )

        filename = artifact["filename"]
        if not isinstance(filename, str) or not filename or filename != Path(filename).name:
            raise RuntimeDependencyProvisionError(f"{name} artifact filename is unsafe")
        if artifact["archive"] != "zip":
            raise RuntimeDependencyProvisionError(f"{name} artifact archive must be zip")
        expected_bytes = artifact["bytes"]
        if not isinstance(expected_bytes, int) or expected_bytes <= 0:
            raise RuntimeDependencyProvisionError(f"{name} artifact size is invalid")
        expected_sha256 = artifact["sha256"]
        if (
            not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        ):
            raise RuntimeDependencyProvisionError(f"{name} artifact SHA-256 is invalid")
        version = artifact["version"]
        if not isinstance(version, str) or not version.strip():
            raise RuntimeDependencyProvisionError(f"{name} artifact version is invalid")
        spdx = artifact["spdx_license"]
        if not isinstance(spdx, str) or _SPDX_RE.fullmatch(spdx) is None:
            raise RuntimeDependencyProvisionError(
                f"{name} artifact license is not a single SPDX identifier"
            )
        if spdx not in _ALLOWED_SPDX_LICENSES:
            raise RuntimeDependencyProvisionError(
                f"{name} artifact license is not in the reviewed allowlist: {spdx}"
            )

        raw_prefix = artifact["strip_prefix"]
        prefix_parts: tuple[str, ...]
        if raw_prefix == "." and name == "ollama":
            prefix_parts = (".",)
        else:
            prefix_parts = _safe_relative_path(
                raw_prefix,
                field="strip prefix",
            ).parts
        if len(prefix_parts) != 1:
            raise RuntimeDependencyProvisionError(
                f"{name} artifact strip prefix must be one directory"
            )
        executables = artifact["expected_executables"]
        if (
            not isinstance(executables, list)
            or not executables
            or any(not isinstance(item, str) for item in executables)
        ):
            raise RuntimeDependencyProvisionError(f"{name} artifact executables are invalid")
        normalized_executables = [
            _safe_relative_path(item, field="executables").as_posix() for item in executables
        ]
        if len({item.casefold() for item in normalized_executables}) != len(normalized_executables):
            raise RuntimeDependencyProvisionError(f"{name} artifact executables contain collisions")

        if name in {"postgres", "node"} and "include" in artifact:
            include = artifact.get("include")
            if (
                not isinstance(include, list)
                or not include
                or any(not isinstance(pattern, str) or not pattern for pattern in include)
            ):
                raise RuntimeDependencyProvisionError(
                    f"{name} artifact include allowlist is invalid"
                )
            for pattern in include:
                if (
                    pattern.startswith(("/", "\\"))
                    or ".." in PurePosixPath(pattern.replace("\\", "/")).parts
                    or PurePosixPath(pattern.replace("\\", "/")).parts[0].endswith(":")
                ):
                    raise RuntimeDependencyProvisionError(
                        f"{name} artifact include pattern is unsafe: {pattern}"
                    )

        if name == "ollama":
            notice = artifact.get("license_notice")
            if not isinstance(notice, dict) or set(notice) != {
                "bytes",
                "filename",
                "sha256",
                "url",
            }:
                raise RuntimeDependencyProvisionError(
                    "ollama license notice fields differ from the reviewed schema"
                )
            _validated_download_url(notice["url"])
            notice_filename = notice["filename"]
            if (
                not isinstance(notice_filename, str)
                or not notice_filename
                or notice_filename != Path(notice_filename).name
                or notice_filename.casefold() == str(filename).casefold()
            ):
                raise RuntimeDependencyProvisionError("ollama license notice filename is unsafe")
            notice_bytes = notice["bytes"]
            if not isinstance(notice_bytes, int) or notice_bytes <= 0:
                raise RuntimeDependencyProvisionError("ollama license notice size is invalid")
            notice_sha256 = notice["sha256"]
            if (
                not isinstance(notice_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", notice_sha256) is None
            ):
                raise RuntimeDependencyProvisionError("ollama license notice SHA-256 is invalid")


def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    """Load and validate a runtime dependency lock."""

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeDependencyProvisionError(
            f"cannot read runtime dependency lock {path}: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeDependencyProvisionError("runtime dependency lock root must be an object")
    validate_lock(parsed)
    return parsed


def _verify_artifact(path: Path, artifact: Mapping[str, Any]) -> None:
    try:
        actual_size = path.stat().st_size
    except OSError as exc:
        raise RuntimeDependencyProvisionError(
            f"cannot inspect runtime artifact {path}: {exc}"
        ) from exc
    expected_size = int(artifact["bytes"])
    if actual_size != expected_size:
        raise RuntimeDependencyProvisionError(
            f"{path.name} size {actual_size} != reviewed {expected_size}"
        )
    actual_sha256 = _sha256_file(path)
    expected_sha256 = str(artifact["sha256"])
    if actual_sha256 != expected_sha256:
        raise RuntimeDependencyProvisionError(
            f"{path.name} SHA-256 {actual_sha256} != reviewed {expected_sha256}"
        )


def _artifact_download_urls(artifact: Mapping[str, Any]) -> list[str]:
    """The reviewed acquisition order: the primary URL, then any reviewed
    fallbacks. Every entry re-passes the host/scheme boundary here so a lock
    that skipped ``validate_lock`` still cannot smuggle in an unapproved
    source."""

    urls = [str(_validated_download_url(artifact.get("url")).geturl())]
    fallback_urls = artifact.get("fallback_urls")
    if isinstance(fallback_urls, Sequence) and not isinstance(fallback_urls, str):
        for item in fallback_urls:
            urls.append(str(_validated_download_url(item).geturl()))
    return urls


def _configured_mirror(mirror: Path | None) -> Path | None:
    if mirror is not None:
        return mirror
    value = os.environ.get(MIRROR_ENV_VAR, "").strip()
    return Path(value) if value else None


def _mirror_entry(mirror: Path, artifact: Mapping[str, Any]) -> Path:
    return mirror / str(artifact["sha256"]) / str(artifact["filename"])


def _admit_to_mirror(
    name: str,
    verified_archive: Path,
    artifact: Mapping[str, Any],
    mirror: Path | None,
) -> None:
    """Best-effort write-through of an already-verified archive into the
    persistent mirror. A mirror write failure (permissions, disk) must never
    fail an acquisition that already holds verified bytes -- it only costs
    resilience on a FUTURE run, so it warns loudly instead."""

    if mirror is None:
        return
    entry = _mirror_entry(mirror, artifact)
    try:
        if entry.is_file():
            try:
                _verify_artifact(entry, artifact)
            except RuntimeDependencyProvisionError:
                pass  # a corrupt entry is rewritten below
            else:
                return
        entry.parent.mkdir(parents=True, exist_ok=True)
        partial = entry.with_name(f"{entry.name}.partial")
        shutil.copyfile(verified_archive, partial)
        _verify_artifact(partial, artifact)
        partial.replace(entry)
    except (OSError, RuntimeDependencyProvisionError) as exc:
        print(
            f"WARNING: could not admit the verified {name} artifact into the "
            f"runtime artifact mirror at {entry}: {exc}",
            file=sys.stderr,
        )


def fetch_locked_artifact(
    name: str,
    artifact: Mapping[str, Any],
    cache: Path,
    *,
    offline: bool = False,
    opener: Callable[..., Any] = urllib.request.urlopen,
    mirror: Path | None = None,
) -> Path:
    """Acquire one reviewed artifact, verifying bytes before cache admission.

    Acquisition order, every step gated by the SAME size+SHA-256 pin:

    1. The run's ``cache`` directory (verified, never trusted bare).
    2. The persistent hash-addressed mirror (``mirror=``, or the
       ``CIVICCAST_RUNTIME_ARTIFACT_MIRROR`` environment variable) at
       ``<mirror>/<sha256>/<filename>`` -- an entry that fails verification
       is ignored here and repaired after a successful download.
    3. The lock's primary ``url``, then each reviewed ``fallback_urls`` entry
       in order. Only when every reviewed source fails does acquisition fail.

    A successful network download is written back into the mirror
    (best-effort) so the pinned bytes survive upstream release pruning.
    """

    urls = _artifact_download_urls(artifact)
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / str(artifact["filename"])
    partial = destination.with_name(f"{destination.name}.partial")
    if destination.exists():
        _verify_artifact(destination, artifact)
        return destination

    mirror_root = _configured_mirror(mirror)
    if mirror_root is not None:
        entry = _mirror_entry(mirror_root, artifact)
        if entry.is_file():
            try:
                _verify_artifact(entry, artifact)
            except RuntimeDependencyProvisionError as exc:
                print(
                    f"WARNING: runtime artifact mirror entry for {name} failed "
                    f"verification and is ignored: {exc}",
                    file=sys.stderr,
                )
            else:
                try:
                    partial.unlink(missing_ok=True)
                    shutil.copyfile(entry, partial)
                    _verify_artifact(partial, artifact)
                    partial.replace(destination)
                except Exception:
                    partial.unlink(missing_ok=True)
                    raise
                return destination

    if offline:
        raise RuntimeDependencyProvisionError(
            f"offline cache is missing reviewed {name} artifact: {destination}"
        )

    failures: list[str] = []
    last_error: Exception | None = None
    for url in urls:
        partial.unlink(missing_ok=True)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "CivicCast-native-runtime-provisioner/1"},
        )
        try:
            with opener(request, timeout=60) as response:
                final_url = response.geturl()
                try:
                    _validated_download_url(final_url)
                except RuntimeDependencyProvisionError as exc:
                    raise RuntimeDependencyProvisionError(
                        f"{name} download redirect refused: {final_url}"
                    ) from exc
                with partial.open("wb") as handle:
                    while chunk := response.read(_CHUNK_BYTES):
                        handle.write(chunk)
            _verify_artifact(partial, artifact)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            if len(urls) == 1:
                raise
            failures.append(f"{url}: {exc}")
            last_error = exc
            continue
        partial.replace(destination)
        _admit_to_mirror(name, destination, artifact, mirror_root)
        return destination
    raise RuntimeDependencyProvisionError(
        f"every reviewed source for the {name} artifact failed: " + "; ".join(failures)
    ) from last_error


def _archive_relative_path(
    member_name: str,
    *,
    strip_prefix: str,
) -> PurePosixPath | None:
    normalized = member_name.replace("\\", "/")
    member = PurePosixPath(normalized)
    parts = member.parts
    if (
        member.is_absolute()
        or not parts
        or ".." in parts
        or parts[0].endswith(":")
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise RuntimeDependencyProvisionError(f"unsafe archive member: {member_name}")
    if strip_prefix == ".":
        return member
    if parts[0] != strip_prefix:
        raise RuntimeDependencyProvisionError(
            f"archive member is outside reviewed prefix {strip_prefix!r}: {member_name}"
        )
    relative_parts = parts[1:]
    if not relative_parts:
        return None
    return PurePosixPath(*relative_parts)


def _matches_include(path: PurePosixPath, include: Sequence[str] | None) -> bool:
    if include is None:
        return True
    value = path.as_posix()
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in include)


def _require_windows_safe_archive_path(path: PurePosixPath, *, member_name: str) -> None:
    for part in path.parts:
        if (
            part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or any(character in _WINDOWS_FORBIDDEN_CHARS for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        ):
            raise RuntimeDependencyProvisionError(f"unsafe Windows archive member: {member_name}")


def _is_transient(path: PurePosixPath) -> bool:
    lowered = tuple(part.casefold() for part in path.parts)
    name = lowered[-1]
    return "__pycache__" in lowered or name.endswith((".pyc", ".pyo", ".tmp", "~"))


def safe_extract_zip(
    archive: Path,
    destination: Path,
    *,
    strip_prefix: str,
    include: Sequence[str] | None = None,
) -> None:
    """Extract an allowlisted ZIP without traversal, links, or NTFS collisions."""

    if destination.exists() or destination.is_symlink():
        raise RuntimeDependencyProvisionError(
            f"refusing existing archive destination: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeDependencyProvisionError(f"cannot open reviewed ZIP {archive}: {exc}") from exc
    with (
        handle,
        tempfile.TemporaryDirectory(
            prefix=f".{destination.name}.extract-", dir=destination.parent
        ) as temporary,
    ):
        staging = Path(temporary) / "payload"
        staging.mkdir()
        seen: dict[str, str] = {}
        for info in handle.infolist():
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeDependencyProvisionError(f"unsafe archive symlink: {info.filename}")
            relative = _archive_relative_path(
                info.filename,
                strip_prefix=strip_prefix,
            )
            if relative is None:
                continue
            if not _matches_include(relative, include) or _is_transient(relative):
                continue
            _require_windows_safe_archive_path(relative, member_name=info.filename)

            target = staging.joinpath(*relative.parts)
            try:
                target.resolve().relative_to(staging.resolve())
            except ValueError as exc:
                raise RuntimeDependencyProvisionError(
                    f"unsafe archive destination: {info.filename}"
                ) from exc
            collision_key = relative.as_posix().casefold()
            previous = seen.get(collision_key)
            if previous is not None:
                if previous == relative.as_posix():
                    raise RuntimeDependencyProvisionError(
                        f"duplicate archive member: {relative.as_posix()!r}"
                    )
                raise RuntimeDependencyProvisionError(
                    f"case-insensitive archive collision: {previous!r} and {relative.as_posix()!r}"
                )
            seen[collision_key] = relative.as_posix()

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists() and target.is_dir():
                raise RuntimeDependencyProvisionError(
                    f"archive file collides with a directory: {info.filename}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
        staging.replace(destination)


def _assert_required_payload(
    name: str,
    root: Path,
    artifact: Mapping[str, Any],
) -> None:
    for executable in artifact["expected_executables"]:
        path = root.joinpath(*PurePosixPath(str(executable)).parts)
        if not path.is_file():
            raise RuntimeDependencyProvisionError(
                f"{name} required executable is missing: {executable}"
            )
    if name == "postgres":
        for license_name in (
            "commandlinetools_3rd_party_licenses.txt",
            "server_license.txt",
        ):
            if not (root / license_name).is_file():
                raise RuntimeDependencyProvisionError(
                    f"postgres required license material is missing: {license_name}"
                )
    elif not any(path.is_file() and "license" in path.name.casefold() for path in root.rglob("*")):
        raise RuntimeDependencyProvisionError(f"{name} required license material is missing")


def _manifest_files(
    root: Path,
    *,
    lock: Mapping[str, Any],
) -> list[dict[str, object]]:
    component_by_root = {
        output_root: (name, artifact)
        for name, output_root in _OUTPUT_ROOTS.items()
        for artifact in (lock["artifacts"][name],)
    }
    rows: list[dict[str, object]] = []
    for path in sorted(
        (candidate for candidate in root.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix()
        if relative in _TRUST_ARTIFACTS:
            continue
        root_name = PurePosixPath(relative).parts[0]
        component = component_by_root.get(root_name)
        if component is None:
            raise RuntimeDependencyProvisionError(
                f"runtime dependency file has no reviewed component owner: {relative}"
            )
        component_name, artifact = component
        rows.append(
            {
                "component": component_name,
                "license": artifact["spdx_license"],
                "path": relative,
                "sha256": _sha256_file(path),
                "size": path.stat().st_size,
                "version": artifact["version"],
            }
        )
    return rows


def _render_sha256sums(rows: Sequence[Mapping[str, object]]) -> str:
    return "".join(
        f"{row['sha256']}  {row['path']}\n"
        for row in sorted(rows, key=lambda row: str(row["path"]))
    )


def _bom_cell(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\r", " ").replace("\n", " ")


def _row_size(row: Mapping[str, object]) -> int:
    value = row["size"]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeDependencyProvisionError(
            f"runtime dependency manifest has an invalid file size: {value!r}"
        )
    return value


def _document_rows(document: Mapping[str, object]) -> list[dict[str, object]]:
    value = document.get("files")
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise RuntimeDependencyProvisionError(
            "runtime dependency manifest has no valid file inventory"
        )
    return cast(list[dict[str, object]], value)


def _render_license_bom(rows: Sequence[Mapping[str, object]]) -> str:
    ordered = sorted(rows, key=lambda row: str(row["path"]))
    by_component: dict[tuple[str, str, str], list[Mapping[str, object]]] = {}
    for row in ordered:
        key = (
            str(row["component"]),
            str(row["version"]),
            str(row["license"]),
        )
        by_component.setdefault(key, []).append(row)

    lines = [
        "# CivicCast (Native) Runtime Dependencies — License Bill of Materials",
        "",
        "Deny-by-default inventory generated from the exact staged manifest. "
        "Every shipped runtime-dependency file is mapped below to one reviewed "
        "component, version, SPDX license, size, and SHA-256. Required upstream "
        "license notices are retained inside each component tree.",
        "",
        "## Summary by component",
        "",
        "| Component | Version | License | Files | Bytes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for (component, version, license_id), group in sorted(by_component.items()):
        lines.append(
            f"| {_bom_cell(component)} | {_bom_cell(version)} | "
            f"{_bom_cell(license_id)} | {len(group)} | "
            f"{sum(_row_size(row) for row in group)} |"
        )
    lines.extend(
        [
            "",
            "## Per-file provenance",
            "",
            "| Path | Component | Version | License | Bytes | SHA-256 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in ordered:
        lines.append(
            f"| {_bom_cell(row['path'])} | {_bom_cell(row['component'])} | "
            f"{_bom_cell(row['version'])} | {_bom_cell(row['license'])} | "
            f"{row['size']} | `{row['sha256']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def _manifest_document(
    root: Path,
    *,
    lock_path: Path,
    lock: Mapping[str, Any],
) -> dict[str, object]:
    rows = _manifest_files(root, lock=lock)
    digests = sorted({str(row["sha256"]) for row in rows})
    return {
        "artifacts": {
            name: {
                "sha256": artifact["sha256"],
                "spdx_license": artifact["spdx_license"],
                "version": artifact["version"],
            }
            for name, artifact in sorted(lock["artifacts"].items())
        },
        "files": rows,
        "lock_sha256": _sha256_file(lock_path),
        "schema_version": 1,
        "sha256_to_paths": {
            digest: sorted(str(row["path"]) for row in rows if row["sha256"] == digest)
            for digest in digests
        },
        "target": lock["target"],
    }


def verify_staged_dependencies(
    root: Path,
    *,
    lock_path: Path = LOCK_PATH,
) -> dict[str, object]:
    """Recompute the exact staged inventory and reject any missing or extra file."""

    manifest_path = root / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeDependencyProvisionError(
            f"cannot read staged dependency manifest {manifest_path}: {exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise RuntimeDependencyProvisionError("staged dependency manifest root must be an object")
    lock = load_lock(lock_path)
    expected = _manifest_document(root, lock_path=lock_path, lock=lock)
    if manifest != expected:
        raise RuntimeDependencyProvisionError(
            "staged dependency tree differs from its reviewed manifest"
        )
    expected_rows = _document_rows(expected)
    expected_trust = {
        SHA256SUMS_NAME: _render_sha256sums(expected_rows),
        LICENSE_BOM_NAME: _render_license_bom(expected_rows),
    }
    for name, expected_text in expected_trust.items():
        path = root / name
        try:
            actual_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RuntimeDependencyProvisionError(
                f"cannot read staged dependency trust artifact {name}: {exc}"
            ) from exc
        if actual_text != expected_text:
            raise RuntimeDependencyProvisionError(
                f"staged dependency trust artifact differs: {name}"
            )
    return manifest


def stage_dependencies(
    lock_path: Path,
    cache: Path,
    output: Path,
    *,
    offline: bool = False,
) -> Path:
    """Reconstruct the reviewed closure in a fresh, transactional output tree."""

    lock_path = lock_path.resolve()
    cache = cache.resolve()
    output = output.resolve()
    lock = load_lock(lock_path)
    if output.exists() and any(output.iterdir()):
        raise RuntimeDependencyProvisionError(
            f"refusing non-empty runtime dependency output directory: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    artifacts = lock["artifacts"]
    acquired = {
        name: fetch_locked_artifact(
            name,
            artifact,
            cache,
            offline=offline,
        )
        for name, artifact in sorted(artifacts.items())
    }
    acquired_notices = {
        name: fetch_locked_artifact(
            f"{name} license notice",
            artifact["license_notice"],
            cache,
            offline=offline,
        )
        for name, artifact in sorted(artifacts.items())
        if "license_notice" in artifact
    }

    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        for name, artifact in sorted(artifacts.items()):
            root = temporary / _OUTPUT_ROOTS[name]
            safe_extract_zip(
                acquired[name],
                root,
                strip_prefix=str(artifact["strip_prefix"]),
                include=artifact.get("include"),
            )
            if name in acquired_notices:
                shutil.copyfile(acquired_notices[name], root / "LICENSE")
            _assert_required_payload(name, root, artifact)

        manifest = _manifest_document(
            temporary,
            lock_path=lock_path,
            lock=lock,
        )
        (temporary / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        manifest_rows = _document_rows(manifest)
        (temporary / SHA256SUMS_NAME).write_text(
            _render_sha256sums(manifest_rows),
            encoding="utf-8",
            newline="\n",
        )
        (temporary / LICENSE_BOM_NAME).write_text(
            _render_license_bom(manifest_rows),
            encoding="utf-8",
            newline="\n",
        )
        if output.exists():
            output.rmdir()
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    verify_staged_dependencies(output, lock_path=lock_path)
    return output / MANIFEST_NAME


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--offline", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = stage_dependencies(
        args.lock,
        args.cache,
        args.output,
        offline=args.offline,
    )
    print(
        json.dumps(
            {
                "manifest": str(manifest.resolve()),
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
