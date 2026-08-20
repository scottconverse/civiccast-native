# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from civiccast.egress import cg_source, slate_source, supervisor
from civiccast.egress.branding import build_branding_filter_plan
from civiccast.egress.cg_bridge import build_cg_overlay_egress_proof
from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.source_plan import SlateSourceGenerator, build_slate_source_args


def test_spec_named_modules_export_existing_egress_contracts() -> None:
    assert slate_source.SlateSourceGenerator is SlateSourceGenerator
    assert slate_source.build_slate_source_args is build_slate_source_args
    assert cg_source.build_branding_filter_plan is build_branding_filter_plan
    assert cg_source.build_cg_overlay_egress_proof is build_cg_overlay_egress_proof
    assert issubclass(supervisor.PlayoutSupervisor, EgressDaemon)
    assert supervisor.PlayoutSupervisor is not EgressDaemon
