# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contributor workflow Pydantic contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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


def _now() -> datetime:
    return datetime(2026, 5, 31, 18, 0, tzinfo=UTC)


def _account() -> ContributorAccount:
    return ContributorAccount(
        account_id="arts-center",
        display_name="Arts Center",
        contact_email="producer@example.test",
        organization="Arts Center",
    )


def _agreement() -> SubmissionAgreementAcceptance:
    return SubmissionAgreementAcceptance(
        agreement_id="community-media-submission",
        version="2026-05-31",
        accepted_at=_now(),
        accepted_by_name="Producer One",
    )


def _media() -> SubmissionMediaReference:
    return SubmissionMediaReference(
        upload_ref="uploads/arts-center/show-one.mov",
        filename="show-one.mov",
        content_type="video/quicktime",
        size_bytes=1024,
        sha256="A" * 64,
    )


def test_contributor_account_must_stay_below_operator_tier() -> None:
    account = _account()

    assert account.tier == "contributor"

    with pytest.raises(ValidationError, match="contributor tier"):
        ContributorAccount(
            account_id="operator-like",
            tier="operator",
            display_name="Operator Like",
            contact_email="operator@example.test",
        )


def test_submission_create_requires_terms_and_notifications() -> None:
    submission = ContributorSubmissionCreate(
        contributor=_account(),
        channel_id="public",
        title="Community Arts Magazine",
        description="A half-hour program from local arts producers.",
        tags=["arts", "community"],
        producer_name="Producer One",
        requested_air_date=_now(),
        media=_media(),
        agreements=[_agreement()],
        notifications=[
            SubmissionNotificationPreference(kind="email", target="producer@example.test")
        ],
    )

    assert submission.agreements[0].agreement_id == "community-media-submission"

    with pytest.raises(ValidationError, match="agreement"):
        ContributorSubmissionCreate(
            contributor=_account(),
            channel_id="public",
            title="Missing Terms",
            description="This payload is incomplete.",
            tags=["community"],
            producer_name="Producer One",
            media=_media(),
            agreements=[],
            notifications=[
                SubmissionNotificationPreference(kind="email", target="producer@example.test")
            ],
        )

    with pytest.raises(ValidationError, match="notification"):
        ContributorSubmissionCreate(
            contributor=_account(),
            channel_id="public",
            title="Missing Notification",
            description="This payload is incomplete.",
            tags=["community"],
            producer_name="Producer One",
            media=_media(),
            agreements=[_agreement()],
            notifications=[],
        )


def test_broken_media_gate_and_review_actions_validate_operator_controls() -> None:
    gate = BrokenMediaGateResult(
        state="passed",
        checked_at=_now(),
        summary="Video and audio probes passed.",
    )
    schedule = ScheduleHandoff(
        channel_id="public",
        requested_start=_now(),
        duration_seconds=1800,
    )
    review = ContributorReviewRequest(
        action="schedule",
        broken_media_gate=gate,
        schedule_handoff=schedule,
    )

    assert review.schedule_handoff is not None
    assert review.schedule_handoff.channel_id == "public"

    with pytest.raises(ValidationError, match="decline_reason"):
        ContributorReviewRequest(action="decline")

    with pytest.raises(ValidationError, match="schedule_handoff"):
        ContributorReviewRequest(action="schedule", broken_media_gate=gate)

    with pytest.raises(ValidationError, match="blocking findings"):
        BrokenMediaGateResult(state="failed", checked_at=_now())
