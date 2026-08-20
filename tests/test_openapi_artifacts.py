# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""OpenAPI-derived API artifact contract tests.

These tests pin the v0.4 Slice 2 substrate: FastAPI OpenAPI is the source of
truth for generated operator API types and the generated API reference.
"""

from __future__ import annotations

import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from civiccast.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate-openapi-artifacts.py"
GENERATED_TYPES = (
    REPO_ROOT / "civiccast" / "apps" / "portal-operator" / "src" / "types" / "api.generated.ts"
)
API_REFERENCE = REPO_ROOT / "docs" / "API-REFERENCE.md"
DOCS_INDEX = REPO_ROOT / "docs" / "index.html"


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)


def _schema_property(schema: dict[str, Any], component: str, prop: str) -> dict[str, Any]:
    return schema["components"]["schemas"][component]["properties"][prop]


def _enum_values(prop_schema: dict[str, Any]) -> set[str]:
    if "enum" in prop_schema:
        return set(prop_schema["enum"])
    if "anyOf" in prop_schema:
        values: set[str] = set()
        for member in prop_schema["anyOf"]:
            values.update(_enum_values(member))
        return values
    return set()


def test_openapi_generated_artifacts_are_current() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--check",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_generated_types_include_slice_2_contract_values() -> None:
    source = GENERATED_TYPES.read_text(encoding="utf-8")

    assert "export interface StaffAssetRow" in source
    assert "'recorded'" in source
    assert "source_live_session_id?: string | null" in source
    assert "mode: 'premiere' | 'embargo'" in source
    assert "state: 'scheduled' | 'cancelled' | 'published'" in source


def test_api_reference_lists_staff_and_public_contracts() -> None:
    source = API_REFERENCE.read_text(encoding="utf-8")

    assert "GET /api/public/assets" in source
    assert "GET /api/staff/assets" in source
    assert "POST /api/staff/schedule" in source
    assert "POST /api/staff/live/sessions" in source
    assert "GET /api/staff/facility/router-inventory" in source
    assert "POST /api/staff/facility/router-take-plan" in source


def test_all_staff_operations_document_auth_throttling_contract() -> None:
    paths = create_app().openapi()["paths"]
    staff_operations = []
    for path, path_item in paths.items():
        if not path.startswith("/api/staff/"):
            continue
        staff_operations.extend(
            operation
            for method, operation in path_item.items()
            if method in {"delete", "get", "patch", "post", "put"}
        )

    assert staff_operations
    for operation in staff_operations:
        response = operation["responses"]["429"]
        assert "failed staff authentication" in response["description"].lower()
        assert response["headers"]["Retry-After"]["schema"] == {"type": "integer"}


def test_caption_review_clip_openapi_declares_inline_wav_binary_response() -> None:
    operation = create_app().openapi()["paths"][
        "/api/staff/captions/review-items/{review_item_id}/clip"
    ]["get"]

    wav_schema = operation["responses"]["200"]["content"]["audio/wav"]["schema"]
    assert wav_schema == {"type": "string", "format": "binary"}
    assert "inline" in operation["responses"]["200"]["description"].lower()
    assert "no-store" in operation["responses"]["200"]["description"].lower()


def test_ai_models_openapi_documents_roles_and_error_responses() -> None:
    """S13 W2/W3: the published contract surfaces the §4.1 differential auth and the
    reachable 400/404/503 outcomes, so the documented behavior cannot drift from the
    enforced behavior (the matching 403/404/400/503 API tests live in
    tests/ai_models/test_router.py)."""
    paths = create_app().openapi()["paths"]

    list_op = paths["/api/staff/ai-models"]["get"]
    feature_op = paths["/api/staff/ai-models/{feature}"]["get"]
    availability_op = paths["/api/staff/ai-models/availability"]["get"]
    select_op = paths["/api/staff/ai-models/{feature}/select"]["post"]

    # W2 — required roles published as an x-required-roles extension on each op.
    assert list_op["x-required-roles"] == ["setup_admin", "meeting_operator"]
    assert feature_op["x-required-roles"] == ["setup_admin", "meeting_operator"]
    assert availability_op["x-required-roles"] == ["setup_admin", "meeting_operator"]
    assert select_op["x-required-roles"] == ["setup_admin"]

    # W3 — reachable error outcomes are declared (not just framework defaults).
    assert "503" in list_op["responses"]
    assert set(feature_op["responses"]) >= {"404", "503"}
    assert set(select_op["responses"]) >= {"400", "404", "503"}


def test_api_reference_documents_ai_models_roles_and_errors() -> None:
    """W2/W3 as rendered in the operator-facing reference doc."""
    source = API_REFERENCE.read_text(encoding="utf-8")

    read_block = source.split("### `GET /api/staff/ai-models/{feature}`", 1)[1].split("###", 1)[0]
    select_block = source.split("### `POST /api/staff/ai-models/{feature}/select`", 1)[1].split(
        "###", 1
    )[0]

    # W2 — READ shows both roles; WRITE shows setup_admin only (no meeting_operator).
    assert "setup_admin or meeting_operator" in read_block
    assert "setup_admin" in select_block
    assert "meeting_operator" not in select_block

    # W3 — the new outcome codes are listed in the rendered Responses line.
    assert "404" in read_block and "503" in read_block
    assert "400" in select_block and "404" in select_block and "503" in select_block


def test_docs_index_exists_and_links_resolve() -> None:
    parser = _HrefParser()
    parser.feed(DOCS_INDEX.read_text(encoding="utf-8"))

    assert parser.hrefs, "docs/index.html must link to maintained docs"
    missing: list[str] = []
    for href in parser.hrefs:
        if "://" in href or href.startswith("#"):
            continue
        target = (DOCS_INDEX.parent / href).resolve()
        if not target.exists():
            missing.append(href)

    assert missing == []


def test_openapi_exposes_closed_contract_enums() -> None:
    schema = create_app().openapi()

    expected = {
        ("StaffAssetRow", "state"): {
            "pending_ingest",
            "ingesting",
            "validated",
            "rejected",
            "recorded",
        },
        ("UploadedAssetResponse", "state"): {
            "pending_ingest",
            "ingesting",
            "validated",
            "rejected",
            "recorded",
        },
        ("AssetMetadataUpdate", "retention_policy"): {
            "default",
            "permanent",
            "meeting",
            "short",
        },
        ("ScheduleItemCreate", "mode"): {"premiere", "embargo"},
        ("ScheduleItemResponse", "mode"): {"premiere", "embargo"},
        ("ScheduleItemResponse", "state"): {"scheduled", "cancelled", "published"},
        ("LiveSessionResponse", "state"): {"idle", "preflight", "on_air", "ending", "recorded"},
        ("LiveSourceCreate", "source_type"): {"rtmp", "rtsp", "ndi", "srt"},
        ("LiveSourceResponse", "source_type"): {"rtmp", "rtsp", "ndi", "srt"},
        ("LiveRelayConfigCreate", "mode"): {
            "local_rtmp",
            "cloud_rtmp_relay",
            "direct_syndication",
        },
        ("LiveRelayConfigResponse", "mode"): {
            "local_rtmp",
            "cloud_rtmp_relay",
            "direct_syndication",
        },
        ("LiveRelayHealthUpdate", "health_state"): {
            "not_configured",
            "ready",
            "degraded",
            "offline",
        },
        ("LiveRelayConfigResponse", "health_state"): {
            "not_configured",
            "ready",
            "degraded",
            "offline",
        },
        ("LiveIngestPath", "mode"): {
            "local_rtmp",
            "cloud_rtmp_relay",
            "direct_syndication",
        },
        ("LiveIngestPath", "health_state"): {
            "not_configured",
            "ready",
            "degraded",
            "offline",
        },
        ("RouterEndpoint", "vendor"): {
            "blackmagic-design",
            "ross-video",
            "utah-scientific",
            "evertz",
            "generic",
        },
        ("RouterEndpoint", "transport"): {"tcp", "udp", "rs232"},
        ("RouterEndpoint", "protocol"): {
            "blackmagic-videohub",
            "ross-rosstalk",
            "utah-scientific",
            "evertz",
            "generic-text",
            "generic-hex",
        },
    }

    for (component, prop), values in expected.items():
        assert _enum_values(_schema_property(schema, component, prop)) == values
