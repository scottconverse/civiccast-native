# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""What the unauthenticated hardware probe is allowed to tell a stranger.

GauntletGate W-3 (Minor) + T4 (Minor) -- the leak and the missing contract that
would have let it widen, fixed together.

W-3: ``GET /api/hardware`` needs no auth by documented design (the installer
sizes the deployment before a station exists -- see
docs/ops/staff-route-protection.md). It returned the probed disk path verbatim,
which defaults to ``Path.home()`` -- so an unauthenticated caller learned the
operating-system account name (``C:\\Users\\Scott``). The endpoint being public
is a design choice; disclosing who is logged in is not part of it.

T4: the three existing tests for this endpoint cover shape, tier value, and
OpenAPI presence -- nothing asserted what it may disclose, so adding a field to
HardwareProbe could have widened the leak with the suite staying green.

The rule these tests pin: the public probe answers "how big is this machine",
never "whose machine is it". The CLI (``civiccast doctor``) still reports the
real path -- it runs on the box, for the person who owns it.
"""

from __future__ import annotations

import getpass
from pathlib import Path

from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.platform.hardware import probe, public_hardware_probe


def _public_probe_json() -> dict:
    response = TestClient(create_app()).get("/api/hardware")
    assert response.status_code == 200
    return response.json()


def test_public_probe_never_contains_the_os_account_name() -> None:
    """No field DERIVED from a filesystem path may carry the account name.

    ``os.hostname`` is excluded deliberately, not to make this pass. It is a
    documented, intentional disclosure ("Network hostname for human
    identification") that names the machine, not its user -- and the two are
    independent. CI proved the distinction matters: the GitHub runner's account
    is ``runner`` and its hostname is ``runnervm3jd5f``, so scanning the whole
    payload reported a leak where the redaction had in fact worked (disk.path
    was correctly ``/``).

    Residual, stated rather than hidden: a station named after a person -- say
    ``scotts-pc`` -- still publishes that hostname. Whether the public probe
    should report a hostname at all is a separate product decision from W-3,
    which was about the probed FILESYSTEM PATH, and is not silently changed
    here.
    """

    body = _public_probe_json()
    username = getpass.getuser()

    scanned = {key: value for key, value in body.items() if key != "os"}
    assert username not in str(scanned), (
        f"GET /api/hardware disclosed the OS account name {username!r} to an "
        "unauthenticated caller. The endpoint is public by design; the person "
        "logged into the machine is not part of that design."
    )
    assert username not in body["disk"]["path"]


def test_public_probe_disk_path_is_a_volume_not_a_home_directory() -> None:
    disk_path = _public_probe_json()["disk"]["path"]
    home = Path.home()

    assert disk_path != str(home)
    assert home.name not in disk_path, (
        f"disk.path {disk_path!r} still carries a component of the home directory path."
    )


def test_public_probe_still_answers_the_question_it_exists_for() -> None:
    """Redaction must not gut the endpoint's actual purpose."""

    body = _public_probe_json()

    assert body["disk"]["path"], "A volume label is still needed to say WHICH disk."
    assert body["disk"]["total_gb"] > 0
    assert body["disk"]["free_gb"] >= 0
    assert body["ram"]["total_gb"] > 0
    assert body["recommended_tier"] in ("tier-0", "tier-1", "tier-1-plus", "tier-2")


def test_the_local_probe_keeps_the_real_path_for_the_operator_on_the_box() -> None:
    """`civiccast doctor` runs locally for the machine's owner; it is not a leak."""

    assert probe().disk.path == str(Path.home())


def test_an_explicitly_probed_path_is_reduced_to_its_anchor_for_the_public_view(
    tmp_path: Path,
) -> None:
    """A NAS or data volume must not leak its directory layout either."""

    public = public_hardware_probe(disk_path=tmp_path)

    assert tmp_path.name not in public.disk.path
    assert public.disk.path == str(Path(tmp_path.anchor))


def test_redaction_is_applied_by_the_route_not_only_available_as_a_helper() -> None:
    """A helper nobody calls is not a fix.

    Compares the live endpoint against the raw probe, so wiring the route back
    to `probe()` fails here rather than silently reintroducing the leak.
    """

    assert _public_probe_json()["disk"]["path"] != probe().disk.path
