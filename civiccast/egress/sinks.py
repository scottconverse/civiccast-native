# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Output sink argument builders for channel egress."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from civiccast.egress.errors import SecretUnresolvedError
from civiccast.egress.models import EgressSinkSpec

SecretResolver = Callable[[str], str | None]


def _file_uri_path(uri: str) -> Path:
    """Resolve a ``file://`` URI to a local Path, Windows-drive aware.

    ``urlsplit`` keeps a leading "/" before a Windows drive letter
    (``file:///C:/x`` -> ``"/C:/x"``); ``Path("/C:/x")`` then resolves against
    the current drive root instead of ``C:\\x``. Shared by HlsSink, LocalTsSink,
    and FileSink (1.0-hardening: the siblings previously carried this gap —
    only HlsSink had the fix, inline).
    """
    raw = urlsplit(uri).path
    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    return Path(raw)


class EgressSink:
    """Base class for FFmpeg output-side sink adapters."""

    #: Whether this sink's program carries the channel's video stream.
    #:
    #: Declared rather than inferred because the HLS relay's argv REQUIRES
    #: video (``-map 0:v:0``) for a video-carrying sink -- a relay child that
    #: probes an input with no video then fails fast instead of silently
    #: emitting audio-only HLS forever (beta.10 U12: the live government relay
    #: locked to audio-only after an 18:46:32 mid-stream restart) -- and
    #: requiring video is wrong for an audio-only sink. Every sink shipped
    #: today carries video (there is no audio-only egress sink mode, and
    #: ``extra_output_args`` cannot express ``-vn``), so this defaults True; an
    #: audio-only variant overrides it False and gets the relay's historical
    #: argv byte-for-byte.
    carries_video: bool = True

    def __init__(
        self,
        spec: EgressSinkSpec,
        *,
        resolve_secret: SecretResolver | None = None,
    ) -> None:
        self.spec = spec
        self._resolve_secret = resolve_secret or (lambda _ref: None)

    def connect_target(self) -> str:
        return self.spec.uri

    def output_args(self) -> list[str]:
        raise NotImplementedError

    def is_connected(self) -> bool:
        return False

    def describe(self) -> str:
        secret_label = " with secret ref" if self.spec.secret_ref else ""
        return f"{self.spec.kind} sink {self.spec.label} -> {self.spec.uri}{secret_label}"

    def _secret_value(self) -> str | None:
        if self.spec.secret_ref is None:
            return None
        value = self._resolve_secret(self.spec.secret_ref)
        if not value:
            raise SecretUnresolvedError(f"secret ref {self.spec.secret_ref} is not resolved")
        return value


class SrtSink(EgressSink):
    """SRT caller sink."""

    def connect_target(self) -> str:
        uri = _append_query_defaults(
            self.spec.uri,
            {
                "mode": "caller",
                "latency": str(self.spec.latency_ms * 1000),
                "linger": "5",
            },
        )
        passphrase = self._secret_value()
        if passphrase is not None:
            uri = _append_query_defaults(uri, {"passphrase": passphrase})
        return uri

    def output_args(self) -> list[str]:
        return [*self.spec.extra_output_args, "-f", "mpegts", self.connect_target()]

    def describe(self) -> str:
        uri = _append_query_defaults(
            self.spec.uri,
            {
                "mode": "caller",
                "latency": str(self.spec.latency_ms * 1000),
                "linger": "5",
            },
        )
        if self.spec.secret_ref is not None:
            uri = _append_query_defaults(uri, {"passphrase": "<redacted>"})
        return f"srt sink {self.spec.label} -> {_redact_query(uri)}"


class RtmpSink(EgressSink):
    """RTMP/RTMPS sink for platform restreams and appliances."""

    def connect_target(self) -> str:
        stream_key = self._secret_value()
        if stream_key is None:
            return self.spec.uri
        return f"{self.spec.uri.rstrip('/')}/{stream_key}"

    def output_args(self) -> list[str]:
        return [*self.spec.extra_output_args, "-f", "flv", self.connect_target()]

    def describe(self) -> str:
        target = self.spec.uri.rstrip("/")
        suffix = "/<secret>" if self.spec.secret_ref else ""
        return f"rtmp sink {self.spec.label} -> {target}{suffix}"


class LocalTsSink(EgressSink):
    """Local MPEG-TS sink for UDP or same-host appliance handoff."""

    def connect_target(self) -> str:
        parsed = urlsplit(self.spec.uri)
        if parsed.scheme == "file":
            return str(_file_uri_path(self.spec.uri))
        return self.spec.uri

    def output_args(self) -> list[str]:
        return [*self.spec.extra_output_args, "-f", "mpegts", self.connect_target()]

    def describe(self) -> str:
        return f"local-ts sink {self.spec.label} -> {self.connect_target()}"


class UdpTsSink(EgressSink):
    """Headend-grade SPTS over UDP (cable automation CA-6).

    Cable headends (Comcast MTD, TelVue HyperCaster, Harmonic Spectrum)
    ingest a constant-multiplex-rate single-program transport stream over
    UDP unicast or multicast. The constant rate itself rides the sink's
    allowlisted ``-muxrate`` extra arg (the mpegts muxer null-pads), and the
    datagram payload defaults to 1316 bytes — seven 188-byte TS packets —
    unless the operator pinned a ``pkt_size`` on the URI themselves.
    """

    default_pkt_size = 1316

    def connect_target(self) -> str:
        return _append_query_defaults(self.spec.uri, {"pkt_size": str(self.default_pkt_size)})

    def is_multicast(self) -> bool:
        host = urlsplit(self.spec.uri).hostname or ""
        first_octet = host.split(".", 1)[0]
        return first_octet.isdigit() and 224 <= int(first_octet) <= 239

    def output_args(self) -> list[str]:
        return [*self.spec.extra_output_args, "-f", "mpegts", self.connect_target()]

    def describe(self) -> str:
        mode = "multicast" if self.is_multicast() else "unicast"
        return f"udp-ts sink {self.spec.label} ({mode}) -> {self.connect_target()}"


class FileSink(EgressSink):
    """MPEG-TS file sink for CI, verification, and optional as-run capture."""

    segment_seconds = 3600

    def connect_target(self) -> str:
        parsed = urlsplit(self.spec.uri)
        if parsed.scheme == "file":
            return str(_file_uri_path(self.spec.uri))
        return self.spec.uri

    def output_args(self) -> list[str]:
        target = self.connect_target()
        if _looks_like_strftime_pattern(target):
            return [
                *self.spec.extra_output_args,
                "-f",
                "segment",
                "-segment_time",
                str(self.segment_seconds),
                "-strftime",
                "1",
                "-reset_timestamps",
                "1",
                target,
            ]
        return [*self.spec.extra_output_args, "-f", "mpegts", target]


class HlsSink(EgressSink):
    """Local rolling live-HLS sink: writes a sliding-window manifest + segments.

    Reuses the ffmpeg ``-f hls`` muxer (the same muxer family as the VOD
    packager's ``pack_vod_asset``), teed off the persistent egress encoder's
    program feed. ``delete_segments`` means ffmpeg itself prunes old segments
    as the window slides (no custom cleanup code needed for the steady-state
    case); ``program_date_time`` lets a resuming player anchor to wall-clock
    time.

    Video is STREAM-COPIED (``-c:v copy``), like every other sink in this
    module (see ``egress.runtime``). It is deliberately NOT re-encoded: a
    re-encode through the bundled H.264 encoders (``libopenh264``,
    ``h264_mf``) strips the A/53 closed-caption SEI, so a captioned channel's
    HLS leg silently lost every caption the upstream embed leg had produced.

    Cadence consequence: ffmpeg's HLS muxer cuts only on a keyframe, and
    ``-hls_time`` is therefore a *target*, not a guarantee -- the real segment
    length follows the video's IDR interval, and stream-copy means this sink
    cannot force keyframes (``-force_key_frames``/``-g`` are encoder-side).
    The "2s segments / 12s window" promise therefore depends on the upstream
    encoder emitting a bounded IDR cadence. For the native GStreamer leg that
    is contractual: ``gst/graph.py`` pins ``openh264enc``'s ``gop-size`` to
    ``segment_seconds`` worth of frames. A channel whose video reaches this
    sink with a longer GOP than ``segment_seconds`` (e.g. an arbitrarily long
    source recording's original GOP, or a branded path that re-encodes
    without an equivalent keyframe pin) will produce correspondingly longer
    segments -- the sink cannot correct that without discarding captions.

    ``self.spec.uri`` is a local directory (validated in
    ``EgressSinkSpec._kind_matches_uri``); ``civiccast.stream.media_router``
    serves it at ``/media/live/{channel_id}/...``.
    """

    segment_seconds = 2
    playlist_size = 6  # 6 x 2s segments = 12s sliding window

    def _directory(self) -> Path:
        parsed = urlsplit(self.spec.uri)
        if parsed.scheme != "file":
            return Path(self.spec.uri)
        return _file_uri_path(self.spec.uri)

    def connect_target(self) -> str:
        return str(self._directory() / "playlist.m3u8")

    def output_args(self) -> list[str]:
        directory = self._directory()
        directory.mkdir(parents=True, exist_ok=True)
        segment_pattern = str(directory / "seg%09d.ts")
        return [
            *self.spec.extra_output_args,
            # Stream-copy the encoded video instead of re-encoding it. A
            # re-encode through the bundled H.264 encoders (libopenh264,
            # h264_mf) strips the A/53 closed-caption SEI, so the HLS leg lost
            # every caption even though the upstream GStreamer embed leg
            # produced it -- the decode-back verifier then saw zero cues on a
            # captioned channel. Copy preserves the SEI byte-for-byte.
            #
            # Cadence consequence: -force_key_frames/-g are encoder-side and
            # are impossible with copy, so the ~2s cut points now depend on the
            # upstream encoder's IDR interval. That interval is contractual:
            # gst/graph.py pins openh264enc's ``gop-size`` to segment_seconds
            # worth of frames. Copy also means the video bitrate is whatever
            # upstream already produced, so -b:v is intentionally absent.
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-f",
            "hls",
            "-hls_time",
            str(self.segment_seconds),
            "-hls_list_size",
            str(self.playlist_size),
            "-hls_flags",
            "delete_segments+append_list+program_date_time+independent_segments",
            "-hls_segment_filename",
            segment_pattern,
            self.connect_target(),
        ]

    def describe(self) -> str:
        return f"hls sink {self.spec.label} -> {self.connect_target()}"


class SdiSink(EgressSink):
    """Declared stub: SDI is delivered by the supervised relay, not a sink."""

    def output_args(self) -> list[str]:
        raise NotImplementedError(
            "Direct SDI output is out of scope for the encoder leg; "
            "configure the channel's SDI output device instead (issue #117) - "
            "the automation driver supervises a BYO-ffmpeg DeckLink relay."
        )


def build_sink(
    spec: EgressSinkSpec,
    *,
    resolve_secret: SecretResolver | None = None,
) -> EgressSink:
    """Build a sink adapter for one validated sink spec."""

    if spec.kind == "srt":
        return SrtSink(spec, resolve_secret=resolve_secret)
    if spec.kind == "rtmp":
        return RtmpSink(spec, resolve_secret=resolve_secret)
    if spec.kind == "local-ts":
        return LocalTsSink(spec, resolve_secret=resolve_secret)
    if spec.kind == "udp-ts":
        return UdpTsSink(spec, resolve_secret=resolve_secret)
    if spec.kind == "file":
        return FileSink(spec, resolve_secret=resolve_secret)
    if spec.kind == "hls":
        return HlsSink(spec, resolve_secret=resolve_secret)
    return SdiSink(spec, resolve_secret=resolve_secret)


def _append_query_defaults(uri: str, defaults: dict[str, str]) -> str:
    parsed = urlsplit(uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    existing = {key.lower() for key, _value in query}
    for key, value in defaults.items():
        if key.lower() not in existing:
            query.append((key, value))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _redact_query(uri: str) -> str:
    parsed = urlsplit(uri)
    redacted: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in {"passphrase", "streamkey", "stream_key", "token", "secret"}:
            redacted.append((key, "<redacted>"))
        else:
            redacted.append((key, value))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(redacted), parsed.fragment)
    )


def _looks_like_strftime_pattern(value: str) -> bool:
    return any(pattern in value for pattern in ("%Y", "%m", "%d", "%H", "%M", "%S"))
