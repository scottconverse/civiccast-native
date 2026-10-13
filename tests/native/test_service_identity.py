# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The restricted service keeps access without granting ordinary users access."""

import hashlib
import struct

from civiccast.native.pgdata_acl import pgdata_dacl_sddl
from civiccast.native.supervisor.control_client import is_trusted_owner


def _service_sid():
    digest = hashlib.sha1("CivicCastSupervisor".upper().encode("utf-16-le")).digest()
    return "S-1-5-80-" + "-".join(str(part) for part in struct.unpack("<5I", digest))


def test_control_client_accepts_only_our_virtual_service_or_existing_admin_owners():
    assert is_trusted_owner(_service_sid())
    assert is_trusted_owner("S-1-5-18")
    assert not is_trusted_owner("S-1-5-80-1-2-3-4-5")
    assert not is_trusted_owner("S-1-5-21-1-2-3-1001")


def test_pgdata_acl_keeps_restricted_service_access_after_admin_repair():
    descriptor = pgdata_dacl_sddl("S-1-5-21-1-2-3-1001")
    assert _service_sid() in descriptor
    assert ";;;BU)" not in descriptor
    assert ";;;AU)" not in descriptor


def test_restricted_service_can_control_its_station_but_other_services_cannot():
    from civiccast.native.supervisor.authz import authorize

    assert authorize("restart", frozenset({"station_service"})).allowed
    assert not authorize("restart", frozenset({"authenticated_users"})).allowed
    assert not authorize("restart", frozenset({"other_service"})).allowed
