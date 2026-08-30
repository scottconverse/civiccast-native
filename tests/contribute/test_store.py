# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contributor submission store tests."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from civiccast.contribute.models import (
    BrokenMediaGateResult,
    ContributorAccount,
    ContributorReviewRequest,
    ContributorSubmissionCreate,
    ScheduleHandoff,
    SubmissionAgreementAcceptance,
    SubmissionMediaReference,
    SubmissionNotificationPreference,
)
from civiccast.contribute.store import (
    ContributorSubmissionStore,
    reap_unreferenced_contributor_uploads,
    resolve_contributor_upload_path,
)


def _now() -> datetime:
    return datetime(2026, 5, 31, 18, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def upload_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """QA-3: store.create_submission now requires ``media.upload_ref`` to
    resolve to a real file inside the configured contributor upload
    directory (and recomputes its sha256 server-side), so every test in this
    module needs a real, isolated upload directory rather than a fabricated
    path or the real machine's default storage location."""
    resolved = tmp_path / "contributor-uploads"
    resolved.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(resolved))
    return resolved


def _real_upload(
    upload_dir: Path,
    name: str = "show-one.mov",
    content: bytes = b"real-contributor-video-bytes",
) -> SubmissionMediaReference:
    """Write a REAL file inside *upload_dir* and describe it accurately.

    ``store.create_submission`` now resolves ``upload_ref`` against the
    contributor upload directory and recomputes ``sha256``/``size_bytes``
    from the file on disk, so a fabricated reference (like the old
    ``uploads/arts-center/show-one.mov`` placeholder) is rejected outright.
    """
    path = upload_dir / name
    path.write_bytes(content)
    return SubmissionMediaReference(
        upload_ref=str(path),
        filename=name,
        content_type="video/quicktime",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _submission_payload(
    upload_dir: Path,
    title: str = "Community Arts Magazine",
) -> ContributorSubmissionCreate:
    media_name = "".join(c.lower() if c.isalnum() else "-" for c in title) + ".mov"
    return ContributorSubmissionCreate(
        contributor=ContributorAccount(
            account_id="arts-center",
            display_name="Arts Center",
            contact_email="producer@example.test",
            organization="Arts Center",
        ),
        channel_id="public",
        title=title,
        description="A half-hour program from local arts producers.",
        tags=["arts", "community"],
        producer_name="Producer One",
        requested_air_date=_now(),
        media=_real_upload(upload_dir, name=media_name),
        agreements=[
            SubmissionAgreementAcceptance(
                agreement_id="community-media-submission",
                version="2026-05-31",
                accepted_at=_now(),
                accepted_by_name="Producer One",
            )
        ],
        notifications=[
            SubmissionNotificationPreference(kind="email", target="producer@example.test")
        ],
    )


def test_store_creates_public_receipt_and_operator_queue(upload_dir: Path) -> None:
    store = ContributorSubmissionStore()

    receipt = store.create_submission(_submission_payload(upload_dir))
    queue = store.list_queue()
    status = store.public_status(receipt.submission_id, receipt.receipt_token)

    assert receipt.proof_boundary == "contributor-submission-to-operator-review-queue"
    assert queue.needs_operator_action == 1
    assert queue.submissions[0].state == "submitted"
    assert queue.submissions[0].agreements[0].version == "2026-05-31"
    assert queue.submissions[0].notifications_sent[0].state == "submitted"
    assert status.status_message.startswith("Your program has been received")
    assert store.notification_outbox().notifications[0].target == "producer@example.test"


def test_store_review_accepts_only_after_media_gate_passes(upload_dir: Path) -> None:
    store = ContributorSubmissionStore()
    receipt = store.create_submission(_submission_payload(upload_dir))

    with pytest.raises(ValueError, match="media gate"):
        store.review_submission(receipt.submission_id, ContributorReviewRequest(action="accept"))

    accepted = store.review_submission(
        receipt.submission_id,
        ContributorReviewRequest(
            action="accept",
            broken_media_gate=BrokenMediaGateResult(
                state="passed",
                checked_at=_now(),
                summary="Video and audio probes passed.",
            ),
            metadata_patch={"title": "Edited Community Arts Magazine"},  # type: ignore[arg-type]
        ),
        ingested_asset_id="contributor-arts-center-abcd1234",
    )

    assert accepted.state == "accepted"
    assert accepted.title == "Edited Community Arts Magazine"
    assert accepted.asset_id == "contributor-arts-center-abcd1234"
    assert [notice.state for notice in accepted.notifications_sent] == ["submitted", "accepted"]
    assert [notice.state for notice in store.notification_outbox().notifications] == [
        "submitted",
        "accepted",
    ]


# ---------------------------------------------------------------------------
# TASK A: acceptance must produce a real library asset, and send-to-schedule
# must produce a real, non-null schedule_item_id. store.review_submission
# never fabricates either -- it takes them as evidence the ROUTER already
# produced by actually running the ffprobe ingest / creating the schedule
# item (see civiccast.contribute.router._ingest_accepted_media /
# _create_real_schedule_item) and refuses the transition otherwise.
# ---------------------------------------------------------------------------


def test_accept_without_a_real_ingested_asset_id_is_refused(upload_dir: Path) -> None:
    store = ContributorSubmissionStore()
    receipt = store.create_submission(_submission_payload(upload_dir))

    with pytest.raises(ValueError, match="ingested into the asset library"):
        store.review_submission(
            receipt.submission_id,
            ContributorReviewRequest(
                action="accept",
                broken_media_gate=BrokenMediaGateResult(
                    state="passed", checked_at=_now(), summary="probes passed"
                ),
            ),
            # ingested_asset_id deliberately omitted -- this is the exact
            # "accept flips state but nothing was ingested" bug the field
            # evidence reported (candidate #17).
        )


def test_schedule_before_accept_is_refused(upload_dir: Path) -> None:
    """A submission with no library asset yet (never accepted, or accept
    never completed a real ingest) cannot be sent to the schedule -- this is
    what stops schedule_item_id from ever coming back null on a reported
    success."""
    store = ContributorSubmissionStore()
    receipt = store.create_submission(_submission_payload(upload_dir))

    with pytest.raises(ValueError, match="must be accepted"):
        store.review_submission(
            receipt.submission_id,
            ContributorReviewRequest(
                action="schedule",
                broken_media_gate=BrokenMediaGateResult(
                    state="passed", checked_at=_now(), summary="probes passed"
                ),
                schedule_handoff=ScheduleHandoff(
                    channel_id="public",
                    requested_start=_now(),
                    duration_seconds=1800,
                ),
            ),
            created_schedule_item_id="11111111-1111-1111-1111-111111111111",
        )


def test_schedule_without_a_real_schedule_item_id_is_refused(upload_dir: Path) -> None:
    store = ContributorSubmissionStore()
    receipt = store.create_submission(_submission_payload(upload_dir))
    store.review_submission(
        receipt.submission_id,
        ContributorReviewRequest(
            action="accept",
            broken_media_gate=BrokenMediaGateResult(
                state="passed", checked_at=_now(), summary="probes passed"
            ),
        ),
        ingested_asset_id="contributor-arts-center-abcd1234",
    )

    with pytest.raises(ValueError, match="real schedule item"):
        store.review_submission(
            receipt.submission_id,
            ContributorReviewRequest(
                action="schedule",
                broken_media_gate=BrokenMediaGateResult(
                    state="passed", checked_at=_now(), summary="probes passed"
                ),
                schedule_handoff=ScheduleHandoff(
                    channel_id="public",
                    requested_start=_now(),
                    duration_seconds=1800,
                ),
            ),
            # created_schedule_item_id deliberately omitted -- this is the
            # exact "scheduled with schedule_item_id: null" bug reported.
        )


def test_schedule_persists_the_real_schedule_item_id_on_the_handoff(upload_dir: Path) -> None:
    store = ContributorSubmissionStore()
    receipt = store.create_submission(_submission_payload(upload_dir))
    store.review_submission(
        receipt.submission_id,
        ContributorReviewRequest(
            action="accept",
            broken_media_gate=BrokenMediaGateResult(
                state="passed", checked_at=_now(), summary="probes passed"
            ),
        ),
        ingested_asset_id="contributor-arts-center-abcd1234",
    )

    scheduled = store.review_submission(
        receipt.submission_id,
        ContributorReviewRequest(
            action="schedule",
            broken_media_gate=BrokenMediaGateResult(
                state="passed", checked_at=_now(), summary="probes passed"
            ),
            schedule_handoff=ScheduleHandoff(
                channel_id="public",
                requested_start=_now(),
                duration_seconds=1800,
            ),
        ),
        created_schedule_item_id="11111111-1111-1111-1111-111111111111",
    )

    assert scheduled.state == "scheduled"
    assert scheduled.schedule_handoff is not None
    assert scheduled.schedule_handoff.schedule_item_id == "11111111-1111-1111-1111-111111111111"
    status = store.public_status(receipt.submission_id, receipt.receipt_token)
    assert status.status_message == (
        "Your program has a real spot on the schedule and will air automatically."
    )
    assert status.schedule_handoff is not None
    assert status.schedule_handoff.schedule_item_id == "11111111-1111-1111-1111-111111111111"


def test_known_producer_ids_includes_durable_identity_regardless_of_state(
    upload_dir: Path,
) -> None:
    # M2: producer existence resolves against durable producer-account IDENTITY (the distinct
    # contributor account_ids across ALL submissions in ANY state), not "has a submission in
    # the pending review queue". A producer whose only submission has been published/declined
    # (no longer needing operator action) still resolves.
    store = ContributorSubmissionStore()
    receipt = store.create_submission(_submission_payload(upload_dir, "Already Aired"))
    store.review_submission(
        receipt.submission_id,
        ContributorReviewRequest(
            action="accept",
            broken_media_gate=BrokenMediaGateResult(
                state="passed", checked_at=_now(), summary="probes passed"
            ),
        ),
        ingested_asset_id="contributor-already-aired-abcd1234",
    )
    store.review_submission(
        receipt.submission_id,
        ContributorReviewRequest(
            action="schedule",
            broken_media_gate=BrokenMediaGateResult(
                state="passed",
                checked_at=_now(),
                summary="probes passed",
            ),
            schedule_handoff=ScheduleHandoff(
                channel_id="public",
                requested_start=_now(),
                duration_seconds=1800,
            ),
        ),
        created_schedule_item_id="11111111-1111-1111-1111-111111111111",
    )

    # The submission is now "scheduled" (out of the needs-action set) but the producer
    # identity persists in the durable ledger.
    assert store.list_queue().needs_operator_action == 0
    assert store.known_producer_ids() == {"arts-center"}


def test_known_producer_ids_rejects_unknown_id(upload_dir: Path) -> None:
    store = ContributorSubmissionStore()
    store.create_submission(_submission_payload(upload_dir))
    assert "no-such-producer" not in store.known_producer_ids()


def test_store_decline_and_schedule_feed_producer_report(upload_dir: Path) -> None:
    store = ContributorSubmissionStore()
    accepted = store.create_submission(_submission_payload(upload_dir, "Community Arts Magazine"))
    declined = store.create_submission(_submission_payload(upload_dir, "Noisy Program"))

    store.review_submission(
        accepted.submission_id,
        ContributorReviewRequest(
            action="accept",
            broken_media_gate=BrokenMediaGateResult(
                state="passed", checked_at=_now(), summary="Video and audio probes passed."
            ),
        ),
        ingested_asset_id="contributor-community-arts-magazine-abcd1234",
    )
    store.review_submission(
        accepted.submission_id,
        ContributorReviewRequest(
            action="schedule",
            broken_media_gate=BrokenMediaGateResult(
                state="passed",
                checked_at=_now(),
                summary="Video and audio probes passed.",
            ),
            schedule_handoff=ScheduleHandoff(
                channel_id="public",
                requested_start=_now(),
                duration_seconds=1800,
            ),
        ),
        created_schedule_item_id="22222222-2222-2222-2222-222222222222",
    )
    store.review_submission(
        declined.submission_id,
        ContributorReviewRequest(
            action="decline",
            decline_reason="Audio is not usable for broadcast.",
        ),
    )

    report = store.producer_report()

    assert report.rows[0].submitted_count == 2
    assert report.rows[0].scheduled_count == 1
    assert report.rows[0].declined_count == 1


# ---------------------------------------------------------------------------
# QA-3 (Major): upload_ref/sha256 must be verified against a real upload,
# never trusted verbatim from client JSON.
# ---------------------------------------------------------------------------


def test_create_submission_rejects_upload_ref_outside_the_upload_directory(
    upload_dir: Path, tmp_path: Path
) -> None:
    """A path that isn't even inside the contributor upload directory (a
    fabricated, nonexistent, or "escaped" reference) must be rejected
    outright, not silently accepted into the submission record."""
    outside_dir = tmp_path / "not-the-upload-dir"
    outside_dir.mkdir()
    outside_file = outside_dir / "elsewhere.mov"
    outside_file.write_bytes(b"attacker-controlled-bytes")

    store = ContributorSubmissionStore()
    payload = _submission_payload(upload_dir)
    payload = payload.model_copy(
        update={
            "media": SubmissionMediaReference(
                upload_ref=str(outside_file),
                filename="elsewhere.mov",
                content_type="video/quicktime",
                size_bytes=len(b"attacker-controlled-bytes"),
                sha256=hashlib.sha256(b"attacker-controlled-bytes").hexdigest(),
            )
        }
    )

    with pytest.raises(ValueError, match="contributor upload directory"):
        store.create_submission(payload)


def test_create_submission_rejects_a_traversal_style_relative_upload_ref(
    upload_dir: Path, tmp_path: Path
) -> None:
    """Task C: the opaque ``upload_ref`` is now a bare filename joined onto
    the contributor upload directory (``resolve_contributor_upload_path``),
    not an already-anchored path -- so a relative ``..`` traversal string
    must still be caught by the containment check after the join+resolve,
    exactly as a fabricated absolute path already is above."""
    secret_dir = tmp_path / "not-the-upload-dir"
    secret_dir.mkdir()
    secret_file = secret_dir / "elsewhere.mov"
    secret_file.write_bytes(b"attacker-controlled-bytes")

    store = ContributorSubmissionStore()
    payload = _submission_payload(upload_dir)
    traversal_ref = os.path.relpath(secret_file, upload_dir)
    payload = payload.model_copy(
        update={
            "media": SubmissionMediaReference(
                upload_ref=traversal_ref,
                filename="elsewhere.mov",
                content_type="video/quicktime",
                size_bytes=len(b"attacker-controlled-bytes"),
                sha256=hashlib.sha256(b"attacker-controlled-bytes").hexdigest(),
            )
        }
    )

    with pytest.raises(ValueError, match="contributor upload directory"):
        store.create_submission(payload)


def test_resolve_contributor_upload_path_joins_a_bare_opaque_token(upload_dir: Path) -> None:
    """The shape the public upload endpoint now issues: no directory
    component at all, resolved by joining onto the upload directory."""
    real_path = upload_dir / "a1b2c3.mov"
    real_path.write_bytes(b"x")

    resolved = resolve_contributor_upload_path("a1b2c3.mov", upload_dir=upload_dir)

    assert resolved == real_path.resolve()


def test_resolve_contributor_upload_path_stays_compatible_with_a_legacy_absolute_ref(
    upload_dir: Path,
) -> None:
    """Submissions recorded before this fix carry a full absolute path as
    ``upload_ref``; Path.__truediv__ leaves an anchored right-hand operand
    unchanged, so those must keep resolving to the exact same file with no
    data migration."""
    real_path = upload_dir / "legacy-absolute-ref.mov"
    real_path.write_bytes(b"x")

    resolved = resolve_contributor_upload_path(str(real_path), upload_dir=upload_dir)

    assert resolved == real_path.resolve()


def test_create_submission_rejects_a_wrong_client_claimed_sha256(upload_dir: Path) -> None:
    """A real file inside the upload directory, but a client-claimed sha256
    that does not match the file's real digest, must be rejected -- the
    client is describing a DIFFERENT file than the one it points at."""
    real_content = b"the-actual-uploaded-bytes"
    real_path = upload_dir / "real-show.mov"
    real_path.write_bytes(real_content)

    store = ContributorSubmissionStore()
    payload = _submission_payload(upload_dir)
    payload = payload.model_copy(
        update={
            "media": SubmissionMediaReference(
                upload_ref=str(real_path),
                filename="real-show.mov",
                content_type="video/quicktime",
                size_bytes=len(real_content),
                sha256="f" * 64,  # deliberately wrong
            )
        }
    )

    with pytest.raises(ValueError, match="sha256"):
        store.create_submission(payload)


def test_create_submission_persists_the_server_recomputed_sha256(upload_dir: Path) -> None:
    """Positive path: the persisted submission's media.sha256 is the
    server-recomputed digest of the real file on disk, not merely an echo
    of whatever the client sent (distinguishing "recomputed" from
    "echoed")."""
    real_content = b"a-real-programme-worth-broadcasting"
    real_path = upload_dir / "real-programme.mov"
    real_path.write_bytes(real_content)
    real_digest = hashlib.sha256(real_content).hexdigest()

    store = ContributorSubmissionStore()
    payload = _submission_payload(upload_dir)
    payload = payload.model_copy(
        update={
            "media": SubmissionMediaReference(
                upload_ref=str(real_path),
                filename="real-programme.mov",
                content_type="video/quicktime",
                # Deliberately WRONG claimed size -- proves the store
                # recomputes rather than trusting the client's number too.
                size_bytes=1,
                sha256=None,  # contributor portal omitted it; store must fill it in
            )
        }
    )

    receipt = store.create_submission(payload)
    persisted = store.get_submission(receipt.submission_id)

    assert persisted.media.sha256 == real_digest
    assert persisted.media.size_bytes == len(real_content)


# ---------------------------------------------------------------------------
# QA-2 (Critical): stale, unreferenced contributor uploads must be reaped.
# ---------------------------------------------------------------------------


def test_reap_deletes_only_old_and_unreferenced_files(upload_dir: Path) -> None:
    store = ContributorSubmissionStore()
    referenced_payload = _submission_payload(upload_dir, "Referenced Program")
    store.create_submission(referenced_payload)
    referenced_path = Path(referenced_payload.media.upload_ref)

    orphan_path = upload_dir / "orphaned-upload.mov"
    orphan_path.write_bytes(b"nobody ever submitted this")

    old_cutoff_ts = time.time() - (72 * 3600)
    os.utime(orphan_path, (old_cutoff_ts, old_cutoff_ts))
    os.utime(referenced_path, (old_cutoff_ts, old_cutoff_ts))

    deleted = reap_unreferenced_contributor_uploads(store, max_age_hours=48)

    assert [p.name for p in deleted] == ["orphaned-upload.mov"]
    assert not orphan_path.exists(), "an unreferenced, stale upload must be reaped"
    assert referenced_path.exists(), (
        "a file referenced by a submission (in ANY state) must survive a reap "
        "even though it is old -- deleting it would corrupt that submission"
    )


def test_reap_leaves_recent_unreferenced_files_alone(upload_dir: Path) -> None:
    """A brand-new orphan (e.g. an upload whose /submissions call hasn't
    landed yet) must not be swept up just because nothing references it."""
    store = ContributorSubmissionStore()
    recent_orphan = upload_dir / "just-uploaded.mov"
    recent_orphan.write_bytes(b"still mid-submission-flow")

    deleted = reap_unreferenced_contributor_uploads(store, max_age_hours=48)

    assert deleted == []
    assert recent_orphan.exists()
