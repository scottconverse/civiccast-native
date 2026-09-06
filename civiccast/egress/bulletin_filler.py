# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Bulletin filler renderer (cable automation CA-3).

Gaps between scheduled programs can show a rotating community bulletin board
(incoming airable bulletins rendered into the board's primary zone) instead of
plain slides. When no active board exists, the legacy per-bulletin slide flow
remains unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import os
import textwrap
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from civiccast.cable.channel import ChannelBranding
from civiccast.cg.board_resolver import ResolvedBoard, airable_bulletins
from civiccast.cg.board_runtime import build_board_snapshot_from_store
from civiccast.cg.board_store import CgBoardStore
from civiccast.cg.feed_fetcher import FeedCache
from civiccast.cg.models import CgBulletinSubmission
from civiccast.egress.board_compositor import (
    ImageResolver,
    board_segment_cache_key,
    build_board_preview_args,
    build_board_segment_args,
)
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import (
    MAX_PLAYLIST_SUBCHAINS,
    EgressConfig,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.runtime import FfmpegRunner
from civiccast.egress.source_plan import SlateSourceGenerator, _escape_drawtext
from civiccast.schedule.store import PostgresAssetStore
from civiccast.stream._ffmpeg import FfmpegError, FfmpegNotFoundError, run_ffmpeg

BulletinsProvider = Callable[[str], Sequence[CgBulletinSubmission]]
BoardProvider = Callable[[str, datetime], ResolvedBoard | None]
#: (channel_id, config) -> board raster for the S15 engine overlay, or None.
#: Takes the config because frame geometry lives on ``canonical_profile``.
BoardOverlayProvider = Callable[[str, "EgressConfig"], Path | None]
BrandingProvider = Callable[[str], ChannelBranding | None]

_DEFAULT_BACKGROUND = "0x1a2744"
_LOG = logging.getLogger(__name__)
_SLIDE_SECONDS = 10
_WRAP_WIDTH = 46

__all__ = [
    "BulletinFillerSourceGenerator",
    "FillerSourceProvider",
    "build_board_overlay_provider",
    "build_bulletin_slide_args",
    "build_filler_source_provider",
]


class BulletinFillerSourceGenerator:
    """Render the approved bulletin rotation as an egress source plan."""

    def __init__(
        self,
        *,
        work_dir: Path,
        bulletins_provider: BulletinsProvider,
        branding_provider: BrandingProvider | None = None,
        board_provider: BoardProvider | None = None,
        ffmpeg_runner: FfmpegRunner = run_ffmpeg,
        slate_generator: SlateSourceGenerator | None = None,
        board_image_resolver: ImageResolver | None = None,
        slide_seconds: int = _SLIDE_SECONDS,
        target_fill_seconds: int = 3600,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._work_dir = work_dir
        self._bulletins_provider = bulletins_provider
        self._branding_provider = branding_provider
        self._board_provider = board_provider
        self._ffmpeg_runner = ffmpeg_runner
        self._slate_generator = slate_generator or SlateSourceGenerator(
            work_dir=work_dir, ffmpeg_runner=ffmpeg_runner
        )
        self._board_image_resolver = board_image_resolver
        self._slide_seconds = slide_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._target_fill_seconds = target_fill_seconds
        # Delta review fix (2026-09-05): above MAX_PLAYLIST_SUBCHAINS PAGES
        # (i.e. more than MAX_PLAYLIST_SUBCHAINS**2 distinct slides), a plan
        # built from every page would itself exceed the segment cap again --
        # see _plan_with_cycle. Tracks which page WINDOW to show on the next
        # fill-plan generation so all pages (and therefore all slides) air
        # across successive generations instead.
        self._rotation_page_offset = 0

    def __call__(self, config: EgressConfig) -> EgressSourcePlan:
        now = self._clock()
        board = self._board_provider(config.channel_id, now) if self._board_provider else None
        if board is None:
            return self._render_slide_plan(config, now=now)
        return self._render_board_plan(config, board, now=now)

    def _render_slide_plan(self, config: EgressConfig, *, now: datetime) -> EgressSourcePlan:
        # Only bulletins inside their [requested_start, requested_end) window
        # air right now; scheduled-for-later and expired ones are filtered out.
        bulletins = airable_bulletins(list(self._bulletins_provider(config.channel_id)), now=now)
        if not bulletins:
            return self._slate_generator(config)
        branding = self._branding(config.channel_id)
        slide_dir = self._work_dir / config.channel_id / "bulletins"
        slide_dir.mkdir(parents=True, exist_ok=True)
        segments: list[EgressSourceSegment] = []
        for bulletin in bulletins:
            slide_path = slide_dir / f"{self._slide_hash(bulletin, branding, config)}.ts"
            if not slide_path.exists():
                self._render_slide(slide_path, config, bulletin, branding)
            segments.append(
                EgressSourceSegment(
                    label=bulletin.title,
                    path=str(slide_path),
                    duration_seconds=self._slide_seconds,
                    kind="cg",
                    source_ref=f"bulletin-{bulletin.submission_id}",
                )
            )
        return self._plan_with_cycle(config, segments)

    def _render_board_plan(
        self,
        config: EgressConfig,
        board: ResolvedBoard,
        *,
        now: datetime,
    ) -> EgressSourcePlan:
        bulletins = airable_bulletins(list(self._bulletins_provider(config.channel_id)), now=now)
        board_bulletins: list[CgBulletinSubmission | None] = list(bulletins) or [None]
        branding = self._branding(config.channel_id)
        profile = config.canonical_profile
        board_dir = self._work_dir / config.channel_id / "board"
        board_dir.mkdir(parents=True, exist_ok=True)

        segments: list[EgressSourceSegment] = []
        for bulletin in board_bulletins:
            key = board_segment_cache_key(
                board=board,
                bulletin=bulletin,
                background_color=self._background(branding),
                station_short_name=branding.short_name if branding else "",
                segment_seconds=float(self._slide_seconds),
                width=profile.width,
                height=profile.height,
                frame_rate=profile.fps,
                now=now,
            )
            segment_path = board_dir / f"{key}.ts"
            if not segment_path.exists():
                # Render to a temp path and atomically publish: writing ffmpeg
                # output straight to the cache path lets a concurrent renderer
                # (or a crash mid-write) leave a partial segment that a later
                # exists() check happily airs (gate finding: cache TOCTOU).
                staging = segment_path.with_name(f".{key}.{os.getpid()}.partial.ts")
                self._render_board_segment(
                    segment_path=staging,
                    config=config,
                    board=board,
                    bulletin=bulletin,
                    branding=branding,
                    now=now,
                )
                staging.replace(segment_path)
            segments.append(
                EgressSourceSegment(
                    label="Board" if bulletin is None else bulletin.title,
                    path=str(segment_path),
                    duration_seconds=self._slide_seconds,
                    kind="cg",
                    source_ref=(
                        "board-empty" if bulletin is None else f"bulletin-{bulletin.submission_id}"
                    ),
                )
            )
        return self._plan_with_cycle(config, segments)

    def _plan_with_cycle(
        self, config: EgressConfig, segments: list[EgressSourceSegment]
    ) -> EgressSourcePlan:
        """Hostile-review redo (2026-09-05 regression from #174, two
        follow-up reviews): this fill plan must never NEED more than
        MAX_PLAYLIST_SUBCHAINS total segments -- gst/bridge.graph_from_config
        truncates a "cg"-kind plan past that many decoder sub-chains as a
        fail-safe. Two earlier passes each fixed one problem and
        reintroduced another: lengthening each slide's own hold duration
        changed what actually airs, and capping the rotation at
        MAX_PLAYLIST_SUBCHAINS distinct slides (truncating the rest) SILENTLY
        DROPPED content for a busy board with more slides than that.

        The shipped fix keeps every slide at its configured ~10s hold and
        never drops one: slides are PAGED into groups of at most
        MAX_PLAYLIST_SUBCHAINS (page k holds slides
        ``MAX_PLAYLIST_SUBCHAINS*k .. MAX_PLAYLIST_SUBCHAINS*k + (MAX_PLAYLIST_SUBCHAINS - 1)``),
        each page pre-rendered into its OWN concatenated rotation file (see
        ``_render_rotation``), and the final plan cycles through ALL pages
        together so every slide airs at least once per cycle -- the total
        segment count (pages x cycles) is still capped at
        MAX_PLAYLIST_SUBCHAINS, so more pages means fewer cycles rather than
        exceeding the pipeline's decoder-subchain limit. Coverage is
        therefore ``cycles * sum(page rotation durations)``, which can fall
        short of ``target_fill_seconds`` for a long rotation or a long
        target; the scaled rollover floor
        (``ChannelAutomationService._check_plan_rollover``) extends the fill
        further for as long as the gap persists, exactly as it does for a
        schedule-derived program plan. A shortfall (more pages than one
        cycle can repeat, or coverage under the target) is logged at
        WARNING -- the operator-visible surface for this condition, same
        posture as every other diagnosability fix in this module (Gate A T4:
        a well-labeled log line IS what reaches an operator or a Gate A
        probe reading the control-plane log)."""
        if not segments:
            return EgressSourcePlan(channel_id=config.channel_id, segments=segments)
        all_pages = [
            segments[i : i + MAX_PLAYLIST_SUBCHAINS]
            for i in range(0, len(segments), MAX_PLAYLIST_SUBCHAINS)
        ]
        windowed = False
        if len(all_pages) > MAX_PLAYLIST_SUBCHAINS:
            # Delta review fix (2026-09-05): more than MAX_PLAYLIST_SUBCHAINS
            # pages (i.e. more than MAX_PLAYLIST_SUBCHAINS**2 = 144 distinct
            # slides) still built more than MAX_PLAYLIST_SUBCHAINS total
            # segments -- ``max(1, MAX_PLAYLIST_SUBCHAINS // len(pages))``
            # floors to 1 once ``len(pages) > MAX_PLAYLIST_SUBCHAINS``, which
            # bounds CYCLES but not the page count itself. Select a rotating
            # WINDOW of at most MAX_PLAYLIST_SUBCHAINS pages instead --
            # advancing the offset every call -- so every page (and
            # therefore every slide) airs across successive fill-plan
            # generations rather than exceeding the segment cap at once.
            windowed = True
            offset = self._rotation_page_offset % len(all_pages)
            pages = [
                all_pages[(offset + i) % len(all_pages)] for i in range(MAX_PLAYLIST_SUBCHAINS)
            ]
            self._rotation_page_offset = (offset + MAX_PLAYLIST_SUBCHAINS) % len(all_pages)
            _LOG.warning(
                "channel %s: bulletin/board rotation has %d distinct slides across "
                "%d pages, above the %d-page cap; rotating a window of %d pages "
                "starting at page %d this generation so every page airs across "
                "successive fill-plan generations instead of exceeding the "
                "segment cap at once.",
                config.channel_id,
                len(segments),
                len(all_pages),
                MAX_PLAYLIST_SUBCHAINS,
                MAX_PLAYLIST_SUBCHAINS,
                offset,
            )
        else:
            pages = all_pages
        page_segments: list[EgressSourceSegment] = []
        for page in pages:
            rotation_seconds = self._slide_seconds * len(page)
            rotation_path = self._render_rotation(config, page)
            page_segments.append(
                EgressSourceSegment(
                    label="Bulletin rotation",
                    path=str(rotation_path),
                    duration_seconds=rotation_seconds,
                    kind="cg",
                    source_ref="bulletin-rotation",
                )
            )
        total_page_seconds = sum(segment.duration_seconds for segment in page_segments)
        max_cycles = max(1, MAX_PLAYLIST_SUBCHAINS // len(page_segments))
        cycles = max(
            1,
            min(max_cycles, int(-(-self._target_fill_seconds // total_page_seconds))),
        )
        coverage_seconds = cycles * total_page_seconds
        if len(pages) > 1 and not windowed:
            _LOG.warning(
                "channel %s: bulletin/board rotation has %d distinct slides, above "
                "the %d-slide-per-rotation cap; paging across %d rotation files "
                "(each holding up to %d slides) so every slide still airs, instead "
                "of dropping the tail past the first %d.",
                config.channel_id,
                len(segments),
                MAX_PLAYLIST_SUBCHAINS,
                len(pages),
                MAX_PLAYLIST_SUBCHAINS,
                MAX_PLAYLIST_SUBCHAINS,
            )
        if coverage_seconds < self._target_fill_seconds:
            _LOG.warning(
                "channel %s: bulletin/board fill covers only %ds (%d x %ds across %d "
                "rotation page(s)) against a %ds target; the rollover mechanism "
                "extends this further if the channel is still on this fill once the "
                "covered window runs out.",
                config.channel_id,
                coverage_seconds,
                cycles,
                total_page_seconds,
                len(pages),
                self._target_fill_seconds,
            )
        else:
            _LOG.info(
                "channel %s: bulletin/board fill covers %ds (%d x %ds across %d "
                "rotation page(s)) against a %ds target.",
                config.channel_id,
                coverage_seconds,
                cycles,
                total_page_seconds,
                len(pages),
                self._target_fill_seconds,
            )
        return EgressSourcePlan(
            channel_id=config.channel_id,
            segments=page_segments * cycles,
        )

    def _render_rotation(self, config: EgressConfig, segments: list[EgressSourceSegment]) -> Path:
        """Concatenate ``segments`` (each already an independently-cached,
        pre-rendered ~``_slide_seconds``-long file) into ONE rotation file,
        cached by a hash of the ordered list of source paths -- a cache hit
        skips the concat entirely, same posture as the individual slide/board
        segment caches above."""
        rotation_dir = self._work_dir / config.channel_id / "rotations"
        rotation_dir.mkdir(parents=True, exist_ok=True)
        key = self._rotation_hash(segments)
        rotation_path = rotation_dir / f"{key}.ts"
        if not rotation_path.exists():
            concat_list = rotation_dir / f"{key}.concat.txt"
            staging = rotation_path.with_name(f".{key}.{os.getpid()}.partial.ts")
            # Delta review fix (2026-09-05): a failed (or crashed-mid-render)
            # concat used to leave the concat-list text file and a partial
            # ``.ts`` behind in the rotations directory forever. Clean up
            # both on ANY exit -- the ``staging.replace`` on success already
            # removes ``staging`` by renaming it away, so this is a no-op
            # then; on failure (or an exception from the ffmpeg call
            # itself) both stray files are removed instead of accumulating.
            try:
                concat_list.write_text(
                    "".join(f"file '{segment.path}'\n" for segment in segments),
                    encoding="utf-8",
                )
                args = [
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_list),
                    "-c",
                    "copy",
                    str(staging),
                ]
                result = self._run_ffmpeg_or_fail_open(
                    args, what=f"bulletin rotation for channel {config.channel_id}"
                )
                if result.returncode != 0:
                    raise SourcePrepareError(
                        f"Could not concatenate the bulletin/board rotation for "
                        f"channel {config.channel_id!r}; inspect FFmpeg output "
                        "before retrying."
                    )
                staging.replace(rotation_path)
            finally:
                concat_list.unlink(missing_ok=True)
                staging.unlink(missing_ok=True)
        return rotation_path

    @staticmethod
    def _rotation_hash(segments: list[EgressSourceSegment]) -> str:
        digest = hashlib.sha256()
        for segment in segments:
            digest.update(segment.path.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()[:24]

    def _render_board_segment(
        self,
        *,
        segment_path: Path,
        config: EgressConfig,
        board: ResolvedBoard,
        bulletin: CgBulletinSubmission | None,
        branding: ChannelBranding | None,
        now: datetime,
    ) -> None:
        profile = config.canonical_profile
        args = build_board_segment_args(
            board=board,
            bulletin=bulletin,
            width=profile.width,
            height=profile.height,
            frame_rate=profile.fps,
            background_color=self._background(branding),
            station_short_name=(branding.short_name if branding else ""),
            segment_seconds=self._slide_seconds,
            out_path=segment_path,
            include_text=True,
            now=now,
            image_resolver=self._board_image_resolver or (lambda _: None),
            codec_args=self._board_codec_args(profile),
        )
        result = self._run_ffmpeg_or_fail_open(
            args, what=f"board segment for channel {config.channel_id}"
        )
        if result.returncode != 0:
            # Mirror the slide-path posture on missing font support: retry with all
            # text disabled so the board can still air as an image-only fallback.
            _LOG.warning(
                "channel %s: board text render failed; retrying image-only. The board "
                "will air WITHOUT its text zones until the host's fonts are fixed.",
                config.channel_id,
            )
            args = build_board_segment_args(
                board=board,
                bulletin=bulletin,
                width=profile.width,
                height=profile.height,
                frame_rate=profile.fps,
                background_color=self._background(branding),
                station_short_name=(branding.short_name if branding else ""),
                segment_seconds=self._slide_seconds,
                out_path=segment_path,
                include_text=False,
                now=now,
                image_resolver=self._board_image_resolver or (lambda _: None),
                codec_args=self._board_codec_args(profile),
            )
            result = self._run_ffmpeg_or_fail_open(
                args, what=f"board segment for channel {config.channel_id}"
            )
        if result.returncode != 0:
            ref = "empty" if bulletin is None else bulletin.submission_id
            raise SourcePrepareError(
                f"Could not render board segment for bulletin {ref!r}; "
                "inspect FFmpeg output before retrying."
            )

    def _run_ffmpeg_or_fail_open(self, args: list[str], *, what: str) -> Any:
        """Run ffmpeg, converting an absent/failed binary into the daemon's contract.

        ``run_ffmpeg`` raises ``FfmpegNotFoundError``/``FfmpegError`` BEFORE returning
        a result when the binary is missing or unusable. Those escaped the filler
        uncaught and crashed the egress service (gate finding QA-1); the daemon
        already treats ``SourcePrepareError`` as "this channel cannot be filled right
        now" and keeps running, so translate into that contract.
        """
        try:
            return self._ffmpeg_runner(args)
        except (FfmpegError, FfmpegNotFoundError) as exc:
            raise SourcePrepareError(
                f"Could not render {what}: FFmpeg is unavailable ({exc}). "
                "Install or repair the bundled FFmpeg runtime; the channel falls "
                "back to its slate until then."
            ) from exc

    @staticmethod
    def _board_codec_args(profile: Any) -> list[str]:
        return [
            "-c:v",
            profile.video_codec,
            "-b:v",
            f"{profile.video_bitrate_kbps}k",
            "-g",
            str(profile.gop_size),
        ]

    def _render_slide(
        self,
        slide_path: Path,
        config: EgressConfig,
        bulletin: CgBulletinSubmission,
        branding: ChannelBranding | None,
    ) -> None:
        args = build_bulletin_slide_args(
            output_path=slide_path,
            config=config,
            bulletin=bulletin,
            branding=branding,
            duration_seconds=self._slide_seconds,
        )
        result = self._run_ffmpeg_or_fail_open(
            args, what=f"bulletin slide {bulletin.submission_id!r}"
        )
        if result.returncode != 0:
            # Mirror the slate generator's posture: a host without usable
            # fonts can still air a plain-color slide rather than dead air.
            _LOG.warning(
                "channel %s: bulletin slide text render failed; retrying image-only. "
                "The bulletin will air WITHOUT its text until the host's fonts are fixed.",
                config.channel_id,
            )
            args = build_bulletin_slide_args(
                output_path=slide_path,
                config=config,
                bulletin=bulletin,
                branding=branding,
                duration_seconds=self._slide_seconds,
                include_text=False,
            )
            result = self._ffmpeg_runner(args)
        if result.returncode != 0:
            raise SourcePrepareError(
                f"Could not render bulletin slide {bulletin.submission_id!r}; "
                "inspect FFmpeg output before retrying."
            )

    def _slide_hash(
        self,
        bulletin: CgBulletinSubmission,
        branding: ChannelBranding | None,
        config: EgressConfig,
    ) -> str:
        digest = hashlib.sha256()
        for part in (
            bulletin.submission_id,
            bulletin.title,
            bulletin.message,
            bulletin.organization,
            branding.color if branding else "",
            branding.short_name if branding else "",
            str(self._slide_seconds),
            config.canonical_profile.model_dump_json(),
        ):
            digest.update(part.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()[:24]

    def _branding(self, channel_id: str) -> ChannelBranding | None:
        if self._branding_provider is None:
            return None
        return self._branding_provider(channel_id)

    @staticmethod
    def _background(branding: ChannelBranding | None) -> str:
        return "0x" + branding.color.lstrip("#") if branding is not None else _DEFAULT_BACKGROUND


class FillerSourceProvider:
    """Per-channel gap filler: branch on the config's fill policy."""

    def __init__(
        self,
        *,
        bulletin_generator: BulletinFillerSourceGenerator,
        slate_generator: SlateSourceGenerator,
    ) -> None:
        self._bulletin_generator = bulletin_generator
        self._slate_generator = slate_generator

    def __call__(self, config: EgressConfig) -> EgressSourcePlan:
        if config.fill_policy == "bulletins":
            return self._bulletin_generator(config)
        return self._slate_generator(config)


def _upload_confinement_root() -> Path | None:
    """Return the configured CivicCast upload root, or None if unconfigured.

    Same env var and resolution convention ``civiccast/schedule/router.py``
    already uses to confine asset paths (``CIVICCAST_UPLOAD_DIR``).
    """
    raw = os.environ.get("CIVICCAST_UPLOAD_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _default_image_resolver(session_factory: Any) -> ImageResolver:
    asset_store = PostgresAssetStore(session_factory)

    def resolve(ref: str) -> Path | None:
        if not isinstance(ref, str) or not ref:
            return None
        row = asset_store.get_staff_row(ref)
        if row is None or row.file_path is None:
            return None
        path = Path(row.file_path).expanduser().resolve()
        # Defense-in-depth confinement (gate finding F-4): file_path is a
        # staff-set DB column, not community-controlled, so this isn't
        # exploitable today -- but a board/bulletin image zone should never
        # be able to resolve to an arbitrary filesystem path outside
        # CivicCast's own upload storage. Fail closed (render without the
        # image, same as an unresolvable ref) rather than serve it.
        upload_root = _upload_confinement_root()
        if upload_root is None or not path.is_relative_to(upload_root):
            _LOG.warning(
                "image zone ref %r resolved to %s, which is outside the "
                "configured CivicCast upload root (%s); refusing to render "
                "it into the board/bulletin.",
                ref,
                path,
                upload_root,
            )
            return None
        return path if path.is_file() else None

    return resolve


def build_filler_source_provider(
    session_factory: Any,
    *,
    work_dir: Path,
) -> FillerSourceProvider:
    """Construct the wired per-channel gap filler (durable bulletin store)."""

    from civiccast.cable.channel import default_channel_profiles
    from civiccast.cg.bulletin_store import PostgresCgBulletinStore

    bulletin_store = PostgresCgBulletinStore(session_factory)
    board_store = CgBoardStore(session_factory)
    feed_cache = FeedCache()

    def board_resolver(channel_id: str, now: datetime) -> ResolvedBoard | None:
        return build_board_snapshot_from_store(
            board_store,
            channel_id,
            now=now,
            cache=feed_cache,
        )

    def _branding(channel_id: str) -> ChannelBranding | None:
        for profile in default_channel_profiles():
            if profile.channel_id == channel_id:
                return profile.branding
        return None

    slate_generator = SlateSourceGenerator(work_dir=work_dir)
    return FillerSourceProvider(
        bulletin_generator=BulletinFillerSourceGenerator(
            work_dir=work_dir,
            bulletins_provider=bulletin_store.list_approved,
            branding_provider=_branding,
            board_provider=board_resolver,
            board_image_resolver=_default_image_resolver(session_factory),
            ffmpeg_runner=run_ffmpeg,
            slate_generator=slate_generator,
        ),
        slate_generator=slate_generator,
    )


def build_board_overlay_provider(
    session_factory: Any,
    *,
    work_dir: Path,
    ffmpeg_runner: FfmpegRunner = run_ffmpeg,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BoardOverlayProvider:
    """Per-channel board raster for the S15 engine overlay leg.

    Returns the cached PNG of the channel's active board (rendered through the
    same compositor internals the filler and preview use), or None when the
    channel has no active board or the render fails — the engine then airs
    without the overlay, and the failure is logged, never silent.

    Geometry comes from the channel's own ``EgressConfig.canonical_profile`` —
    the same source the filler renders against, so the overlay raster always
    matches the encoded frame. ``ChannelProfile`` (the branding lineup) carries
    no frame geometry; reading it for width/height/fps raised AttributeError on
    every configured channel (gate finding: crash instead of fail-open).

    ``clock`` exists so a caller can pin the wall time this provider reads.
    A board carrying a clock zone folds ``now`` (truncated to the minute) into
    its cache key on purpose -- the overlay must re-render when the displayed
    minute changes. That makes two back-to-back calls return different cache
    keys whenever they straddle a minute boundary, which is correct in
    production and unreproducible in a test that asserts a cache hit. Injecting
    the clock makes that dependency explicit instead of implicit; the default
    is the same ``datetime.now(UTC)`` the closure used before.
    """

    from civiccast.cable.channel import default_channel_profiles
    from civiccast.cg.bulletin_store import PostgresCgBulletinStore

    board_store = CgBoardStore(session_factory)
    bulletin_store = PostgresCgBulletinStore(session_factory)
    feed_cache = FeedCache()
    image_resolver = _default_image_resolver(session_factory)

    def provider(channel_id: str, config: EgressConfig) -> Path | None:
        now = clock()
        board = build_board_snapshot_from_store(
            board_store,
            channel_id,
            now=now,
            cache=feed_cache,
        )
        if board is None:
            return None
        frame = config.canonical_profile
        width, height, fps = frame.width, frame.height, frame.fps
        branding = next(
            (p.branding for p in default_channel_profiles() if p.channel_id == channel_id),
            None,
        )
        background = (
            "0x" + branding.color.lstrip("#") if branding is not None else _DEFAULT_BACKGROUND
        )
        short_name = branding.short_name if branding is not None else ""
        airable = airable_bulletins(list(bulletin_store.list_approved(channel_id)), now=now)
        bulletin = airable[0] if airable else None
        key = board_segment_cache_key(
            board=board,
            bulletin=bulletin,
            background_color=background,
            station_short_name=short_name,
            segment_seconds=0.0,
            width=width,
            height=height,
            frame_rate=fps,
            now=now,
        )
        out_path = work_dir / channel_id / "board-overlay" / f"{key}.png"
        if not out_path.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                ffmpeg_runner(
                    build_board_preview_args(
                        board=board,
                        bulletin=bulletin,
                        width=width,
                        height=height,
                        frame_rate=fps,
                        background_color=background,
                        station_short_name=short_name,
                        out_path=out_path,
                        include_text=True,
                        now=now,
                        image_resolver=image_resolver,
                    )
                )
            except Exception:
                _LOG.exception(
                    "channel %s: board overlay raster failed to render; airing without it.",
                    channel_id,
                )
                return None
        return out_path

    return provider


def build_bulletin_slide_args(
    *,
    output_path: Path,
    config: EgressConfig,
    bulletin: CgBulletinSubmission,
    branding: ChannelBranding | None,
    duration_seconds: int,
    include_text: bool = True,
) -> list[str]:
    """Build FFmpeg args for one canonical MPEG-TS bulletin slide."""

    profile = config.canonical_profile
    background = "0x" + branding.color.lstrip("#") if branding is not None else _DEFAULT_BACKGROUND
    video_input = (
        f"color=c={background}:size={profile.width}x{profile.height}"
        f":rate={profile.fps}:duration={duration_seconds}"
    )
    args = [
        "-f",
        "lavfi",
        "-i",
        video_input,
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={profile.audio_sample_rate}:cl=stereo",
    ]
    if include_text:
        title = _escape_drawtext(bulletin.title)
        body = _escape_drawtext(textwrap.fill(bulletin.message, width=_WRAP_WIDTH))
        organization = _escape_drawtext(bulletin.organization)
        filters = [
            (
                f"drawtext=expansion=none:text='{title}':fontsize=40:fontcolor=white:"
                "box=1:boxcolor=black@0.4:boxborderw=10:x=(w-text_w)/2:y=h*0.18"
            ),
            (
                f"drawtext=expansion=none:text='{body}':fontsize=26:fontcolor=white:"
                "box=1:boxcolor=black@0.4:boxborderw=8:"
                "line_spacing=10:x=(w-text_w)/2:y=h*0.42"
            ),
            (
                f"drawtext=expansion=none:text='{organization}':fontsize=20:fontcolor=white@0.85:"
                "x=(w-text_w)/2:y=h*0.86"
            ),
        ]
        if branding is not None:
            bug = _escape_drawtext(branding.short_name)
            filters.append(
                f"drawtext=expansion=none:text='{bug}':fontsize=22:fontcolor=white@0.85:"
                "box=1:boxcolor=black@0.35:boxborderw=6:x=w-text_w-24:y=24"
            )
        args.extend(["-vf", ",".join(filters)])
    args.extend(
        [
            "-c:v",
            profile.video_codec,
            "-b:v",
            f"{profile.video_bitrate_kbps}k",
            "-g",
            str(profile.gop_size),
            "-c:a",
            profile.audio_codec,
            "-b:a",
            f"{profile.audio_bitrate_kbps}k",
            "-ar",
            str(profile.audio_sample_rate),
            "-ac",
            str(profile.audio_channels),
            "-shortest",
            "-f",
            "mpegts",
            str(output_path),
        ]
    )
    return args
