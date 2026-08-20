# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the real RFC 3161 Time-Stamp Protocol client.

We never hit a network in unit tests — the production code POSTs to a TSA
endpoint, but the tests inject an ``httpx.MockTransport`` that returns a
synthetic ``TimeStampResp`` DER blob we build with ``asn1crypto`` directly.
The synthetic blob is structurally what a real TSA returns (correct outer
SignedData wrapping a TSTInfo with the right messageImprint); we do NOT
mint a cryptographically-valid signer signature, because the verifier in
``rfc3161.py`` checks digest binding + TSTInfo content rather than the
SignedData signature itself (chain verification is a documented follow-up).
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from asn1crypto import cms, core, tsp

from civiccast.records.models import Rfc3161TimestampProof
from civiccast.records.rfc3161 import (
    DEFAULT_TSA_URL,
    Rfc3161HttpAuthority,
    Rfc3161ProtocolError,
    Rfc3161TransportError,
    Rfc3161VerificationError,
    _build_request,
    _extract_tst_info,
    verify_rfc3161_proof,
)

_TEST_TSA_URL = "https://tsa.test/tsr"


def _make_signed_data_token(
    *, payload: bytes, nonce: int, policy_oid: str, gen_time: datetime
) -> bytes:
    """Build a structurally-valid ``TimeStampToken`` DER blob.

    A real TSA would sign the TSTInfo with its private key and include the
    signing certificate in ``certificates``. Our decoder does NOT verify the
    signature (that's the chain-verification follow-up), so we emit an empty
    signature OCTET STRING and an empty SignerInfo. The structure still
    decodes cleanly + carries the TSTInfo our verifier reads.
    """
    digest_bytes = hashlib.sha256(payload).digest()
    tst_info = tsp.TSTInfo(
        {
            "version": "v1",
            "policy": policy_oid,
            "message_imprint": {
                "hash_algorithm": {"algorithm": "sha256"},
                "hashed_message": digest_bytes,
            },
            "serial_number": 4242,
            "gen_time": gen_time.replace(tzinfo=UTC) if gen_time.tzinfo is None else gen_time,
            "nonce": nonce,
        }
    )
    tst_info_der = tst_info.dump()

    # Wrap the TSTInfo in an EncapsulatedContentInfo with the tsp OID
    # (1.2.840.113549.1.9.16.1.4 = id-ct-TSTInfo).
    encap = cms.EncapsulatedContentInfo(
        {"content_type": "tst_info", "content": core.ParsableOctetString(tst_info_der)}
    )

    # SignedData with empty certs + empty signers (we are not signature-
    # verifying in this slice). digest_algorithms is required and matches the
    # imprint hash algorithm.
    signed_data = cms.SignedData(
        {
            "version": "v3",
            "digest_algorithms": [{"algorithm": "sha256"}],
            "encap_content_info": encap,
            "signer_infos": [],
        }
    )

    # ContentInfo with id-signedData = 1.2.840.113549.1.7.2
    content_info = cms.ContentInfo({"content_type": "signed_data", "content": signed_data})
    return content_info.dump()


def _make_resp(
    *,
    payload: bytes,
    nonce: int,
    policy_oid: str = "1.2.3.4.1",
    status: int = 0,
    gen_time: datetime | None = None,
    include_token: bool = True,
) -> bytes:
    """Build a synthetic ``TimeStampResp`` DER blob the production decoder
    accepts.
    """
    if gen_time is None:
        gen_time = datetime(2026, 6, 18, 14, 30, 0, tzinfo=UTC)
    resp: dict = {
        "status": {"status": status},
    }
    if include_token:
        token_der = _make_signed_data_token(
            payload=payload, nonce=nonce, policy_oid=policy_oid, gen_time=gen_time
        )
        # The TimeStampResp's `time_stamp_token` field is a ContentInfo
        # (parsed from its DER bytes).
        resp["time_stamp_token"] = cms.ContentInfo.load(token_der)
    return tsp.TimeStampResp(resp).dump()


def _mock_transport(handler):
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRequestBuild:
    def test_round_trip(self) -> None:
        req = _build_request(b"hello", policy_oid=None, nonce=42)
        parsed = tsp.TimeStampReq.load(req)
        assert parsed["version"].native == "v1"
        assert int(parsed["nonce"].native) == 42
        assert parsed["cert_req"].native is True
        algo = parsed["message_imprint"]["hash_algorithm"]["algorithm"].native
        assert algo == "sha256"
        assert (
            parsed["message_imprint"]["hashed_message"].native == hashlib.sha256(b"hello").digest()
        )

    def test_policy_included_when_pinned(self) -> None:
        req = _build_request(b"x", policy_oid="1.2.3.4.5", nonce=7)
        parsed = tsp.TimeStampReq.load(req)
        assert str(parsed["req_policy"].native) == "1.2.3.4.5"

    def test_policy_absent_when_none(self) -> None:
        req = _build_request(b"x", policy_oid=None, nonce=7)
        parsed = tsp.TimeStampReq.load(req)
        assert parsed["req_policy"].native is None


class TestRoundTripAgainstSyntheticTsa:
    def _client_with(self, handler) -> Rfc3161HttpAuthority:
        client = httpx.Client(transport=_mock_transport(handler))
        return Rfc3161HttpAuthority(
            tsa_url=_TEST_TSA_URL,
            policy_oid="1.2.3.4.1",
            http_client=client,
        )

    def test_happy_path(self) -> None:
        payload = b"signed-record bytes"
        captured_nonce: dict[str, int] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["content-type"] == "application/timestamp-query"
            parsed = tsp.TimeStampReq.load(request.content)
            captured_nonce["n"] = int(parsed["nonce"].native)
            body = _make_resp(payload=payload, nonce=captured_nonce["n"])
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/timestamp-reply"},
            )

        auth = self._client_with(handler)
        proof = auth.timestamp(payload)

        assert proof.algorithm == "sha256"
        assert proof.artifact_digest == "sha256:" + hashlib.sha256(payload).hexdigest()
        assert proof.tsa_policy_oid == "1.2.3.4.1"
        assert proof.tsa_url == _TEST_TSA_URL
        assert proof.serial_number == "4242"
        assert proof.timestamped_at.tzinfo is not None
        # Token round-trips
        token_der = base64.b64decode(proof.token_der_b64)
        tst = _extract_tst_info(token_der)
        assert int(tst["nonce"].native) == captured_nonce["n"]
        assert verify_rfc3161_proof(payload, proof) is True

    def test_rejected_status(self) -> None:
        payload = b"x"

        def handler(request: httpx.Request) -> httpx.Response:
            body = _make_resp(payload=payload, nonce=0, status=2, include_token=False)
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/timestamp-reply"},
            )

        auth = self._client_with(handler)
        with pytest.raises(Rfc3161ProtocolError, match="rejection"):
            auth.timestamp(payload)

    def test_response_without_token_when_accepted_is_protocol_error(self) -> None:
        payload = b"x"

        def handler(request: httpx.Request) -> httpx.Response:
            body = _make_resp(payload=payload, nonce=0, status=0, include_token=False)
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/timestamp-reply"},
            )

        auth = self._client_with(handler)
        with pytest.raises(Rfc3161ProtocolError, match="omitted the timeStampToken"):
            auth.timestamp(payload)

    def test_response_with_wrong_digest_is_rejected(self) -> None:
        """A malicious or buggy TSA that signs a DIFFERENT document must
        not produce a proof we accept."""
        our_payload = b"the real document"

        def handler(request: httpx.Request) -> httpx.Response:
            # TSA "signs" a different payload (attack scenario).
            body = _make_resp(payload=b"a different document", nonce=99)
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/timestamp-reply"},
            )

        auth = self._client_with(handler)
        with pytest.raises(Rfc3161VerificationError, match="does not bind"):
            auth.timestamp(our_payload)

    def test_nonce_mismatch_is_rejected(self) -> None:
        payload = b"x"

        def handler(request: httpx.Request) -> httpx.Response:
            # TSA echoes a different nonce (response swap).
            body = _make_resp(payload=payload, nonce=11111111111111)
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/timestamp-reply"},
            )

        auth = self._client_with(handler)
        with pytest.raises(Rfc3161VerificationError, match="nonce does not match"):
            auth.timestamp(payload)

    def test_wrong_content_type_is_protocol_error(self) -> None:
        payload = b"x"

        def handler(request: httpx.Request) -> httpx.Response:
            body = _make_resp(payload=payload, nonce=1)
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "text/html"},
            )

        auth = self._client_with(handler)
        with pytest.raises(Rfc3161ProtocolError, match="content-type"):
            auth.timestamp(payload)

    def test_garbage_response_body_is_protocol_error(self) -> None:
        payload = b"x"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"not asn.1 at all",
                headers={"content-type": "application/timestamp-reply"},
            )

        auth = self._client_with(handler)
        with pytest.raises(Rfc3161ProtocolError, match="not a parseable TimeStampResp"):
            auth.timestamp(payload)

    def test_transport_failure(self) -> None:
        payload = b"x"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, content=b"")

        auth = self._client_with(handler)
        with pytest.raises(Rfc3161TransportError):
            auth.timestamp(payload)


class TestVerifyProof:
    def test_round_trip(self) -> None:
        payload = b"binding test"
        # Build a known-good proof.
        token_der = _make_signed_data_token(
            payload=payload,
            nonce=77,
            policy_oid="1.2.3.4.1",
            gen_time=datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC),
        )
        proof = Rfc3161TimestampProof(
            algorithm="sha256",
            artifact_digest="sha256:" + hashlib.sha256(payload).hexdigest(),
            token_der_b64=base64.b64encode(token_der).decode(),
            timestamped_at=datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC),
            tsa_policy_oid="1.2.3.4.1",
            nonce="77",
        )
        assert verify_rfc3161_proof(payload, proof) is True

    def test_modified_payload_rejected(self) -> None:
        original = b"binding test"
        modified = b"binding test (tampered)"
        token_der = _make_signed_data_token(
            payload=original,
            nonce=77,
            policy_oid="1.2.3.4.1",
            gen_time=datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC),
        )
        proof = Rfc3161TimestampProof(
            algorithm="sha256",
            artifact_digest="sha256:" + hashlib.sha256(original).hexdigest(),
            token_der_b64=base64.b64encode(token_der).decode(),
            timestamped_at=datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC),
            tsa_policy_oid="1.2.3.4.1",
            nonce="77",
        )
        with pytest.raises(Rfc3161VerificationError):
            verify_rfc3161_proof(modified, proof)

    def test_swapped_token_for_different_payload_rejected(self) -> None:
        """An attacker swaps the token_der_b64 for one that was issued for
        a different document. The proof's recorded artifact_digest still
        matches the new document, but the token's embedded TSTInfo binds
        to the OLD document — should be rejected.
        """
        original = b"document A"
        attack = b"document B"
        # Token was issued for original (document A).
        token_der = _make_signed_data_token(
            payload=original,
            nonce=1,
            policy_oid="1.2.3.4.1",
            gen_time=datetime.now(UTC),
        )
        # Attacker rewrites the proof to claim it binds to attack
        # (document B), keeping the original token.
        proof = Rfc3161TimestampProof(
            algorithm="sha256",
            artifact_digest="sha256:" + hashlib.sha256(attack).hexdigest(),
            token_der_b64=base64.b64encode(token_der).decode(),
            timestamped_at=datetime.now(UTC),
            tsa_policy_oid="1.2.3.4.1",
            nonce="1",
        )
        with pytest.raises(Rfc3161VerificationError, match="does not bind"):
            verify_rfc3161_proof(attack, proof)

    def test_bad_base64_rejected(self) -> None:
        proof = Rfc3161TimestampProof(
            algorithm="sha256",
            artifact_digest="sha256:" + "00" * 32,
            token_der_b64="!!!not base64!!!",
            timestamped_at=datetime.now(UTC),
        )
        with pytest.raises(Rfc3161VerificationError, match="not valid base64"):
            verify_rfc3161_proof(b"", proof)


class TestEnvDefaults:
    def test_default_url_used_when_no_env(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.delenv("CIVICCAST_TSA_URL", raising=False)
        auth = Rfc3161HttpAuthority()
        assert auth._tsa_url == DEFAULT_TSA_URL

    def test_env_url_picked_up(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TSA_URL", "https://example.test/tsr")
        auth = Rfc3161HttpAuthority()
        assert auth._tsa_url == "https://example.test/tsr"

    def test_explicit_overrides_env(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("CIVICCAST_TSA_URL", "https://env.test/tsr")
        auth = Rfc3161HttpAuthority(tsa_url="https://explicit.test/tsr")
        assert auth._tsa_url == "https://explicit.test/tsr"
