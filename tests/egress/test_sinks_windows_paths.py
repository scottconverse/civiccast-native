# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows file:// path resolution across ALL file-target sinks (1.0-hardening).

The drive-letter gap (urlsplit keeps the leading "/" before "C:") was fixed
inline in HlsSink only; LocalTsSink and FileSink carried the same shortcut
untested. One shared helper now serves all three — these tests pin it per sink.
"""

from __future__ import annotations

from civiccast.egress.models import EgressSinkSpec
from civiccast.egress.sinks import FileSink, HlsSink, LocalTsSink, _file_uri_path


def test_file_uri_path_strips_windows_drive_slash() -> None:
    assert str(_file_uri_path("file:///C:/CivicCast/out")).replace("\\", "/") == "C:/CivicCast/out"


def test_file_uri_path_keeps_posix_paths() -> None:
    assert str(_file_uri_path("file:///var/civiccast/out")).replace("\\", "/") == (
        "/var/civiccast/out"
    )


def test_local_ts_sink_resolves_windows_file_uri() -> None:
    sink = LocalTsSink(
        EgressSinkSpec(kind="local-ts", label="ts", uri="file:///C:/CivicCast/out.ts")
    )
    assert sink.connect_target().replace("\\", "/") == "C:/CivicCast/out.ts"


def test_file_sink_resolves_windows_file_uri() -> None:
    sink = FileSink(EgressSinkSpec(kind="file", label="f", uri="file:///C:/CivicCast/out.ts"))
    assert sink.connect_target().replace("\\", "/") == "C:/CivicCast/out.ts"


def test_hls_sink_resolves_windows_file_uri() -> None:
    sink = HlsSink(EgressSinkSpec(kind="hls", label="h", uri="file:///C:/CivicCast/live"))
    assert sink.connect_target().replace("\\", "/") == "C:/CivicCast/live/playlist.m3u8"
