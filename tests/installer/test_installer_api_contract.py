# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for staff-only cross-platform installer API responses."""

from __future__ import annotations

from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.installer import service


class TestInstallerApiContract:
    def test_platform_plan_endpoint_requires_staff_auth(self) -> None:
        client = TestClient(create_app())

        response = client.get("/api/staff/installer/platform-plan")

        assert response.status_code != 404
        assert response.status_code in {401, 403}
        staff_client = TestClient(
            create_app(), headers={"Authorization": "Bearer operator-token-a"}
        )
        staff_response = staff_client.get(
            "/api/staff/installer/platform-plan",
            params={"os_family": "linux"},
        )
        assert staff_response.status_code == 200

    def test_platform_plan_endpoint_returns_closed_response_model(self) -> None:
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.get(
            "/api/staff/installer/platform-plan",
            params={"os_family": "linux"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["runtime"] == "native-linux"
        assert payload["model_config"]["extra"] == "forbid"
        assert payload["service_metadata"]["manager"] == "systemd"

    def test_platform_plan_endpoint_rejects_the_retired_windows_os_family(self) -> None:
        """Windows deployment readiness is decided by the native-station
        signals in build_installer_summary now, never by this generic
        multi-OS plan -- os_family no longer accepts "windows" at all."""

        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.get(
            "/api/staff/installer/platform-plan",
            params={"os_family": "windows"},
        )

        assert response.status_code == 422

    def test_package_verification_endpoint_blocks_missing_proof(self) -> None:
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.post(
            "/api/staff/installer/package-verification",
            json={"artifact": "missing.deb", "sidecar": "missing.deb.sidecar.json"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "blocked"
        assert payload["ready"] is False
        assert "rebuild the package artifact" in payload["next_step"].lower()

    def test_model_state_endpoint_does_not_ready_when_model_proof_missing(self) -> None:
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.get("/api/staff/installer/model-state")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ready"] is False
        assert any(item["proof_state"] == "proof_unavailable" for item in payload["items"])

    def test_airgap_endpoint_does_not_ready_when_airgap_proof_missing(self) -> None:
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.post(
            "/api/staff/installer/airgap-import",
            json={"bundle_dir": "missing-bundle", "network_enabled": False},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "blocked"
        assert payload["ready"] is False
        assert "proof" in payload["next_step"].lower()

    def test_airgap_endpoint_rejects_proof_manifest_outside_bundle(self, tmp_path) -> None:
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        outside = tmp_path / "outside-proof.json"
        outside.write_text("{}", encoding="utf-8")

        response = client.post(
            "/api/staff/installer/airgap-import",
            json={
                "bundle_dir": str(bundle),
                "proof_manifest": str(outside),
                "network_enabled": False,
            },
        )

        assert response.status_code == 422
        assert "inside bundle_dir" in response.json()["detail"]

    def test_installer_summary_reports_local_setup_lanes(self) -> None:
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.get("/api/staff/installer/summary")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ready"] is False
        assert payload["platform"] in {"linux", "macos", "windows-native"}
        assert {
            "platform",
            "runtime",
            "ffmpeg",
            "ndi",
            "storage",
            "secrets",
            "service",
            "dashboard",
        } == {lane["id"] for lane in payload["lanes"]}

    def test_installer_summary_maps_every_windows_host_to_native_platform(
        self,
        monkeypatch,
    ) -> None:
        """Every Windows control plane running today's code is the native
        station -- the retired WSL2 lane's own control plane always ran as a
        Linux process, so `platform.system() == "Windows"` alone is now a
        reliable signal on its own, with no ambiguous fallback."""

        monkeypatch.setattr(service.platform, "system", lambda: "Windows")

        summary = service.build_installer_summary()

        assert summary.platform == "windows-native"

    @staticmethod
    def _force_ready_host(monkeypatch, *, ffmpeg: bool) -> None:
        """Put the summary on a Linux host whose required lanes all pass."""

        monkeypatch.setattr(service.platform, "system", lambda: "Linux")
        ready_plan = service.build_bootstrap_plan(
            os_family="linux",
            detected_tools={"systemd": True, "package_manager": "apt"},
        )
        monkeypatch.setattr(service, "_detected_bootstrap_plan", lambda: ready_plan)
        ready_storage = service.durable_storage_status().model_copy(
            update={"status": "ready", "migrations_applied": True}
        )
        monkeypatch.setattr(service, "durable_storage_status", lambda: ready_storage)
        real_which = service.shutil.which
        monkeypatch.setattr(
            service.shutil,
            "which",
            lambda name, *args, **kwargs: (
                ((real_which(name, *args, **kwargs) or "/usr/bin/ffmpeg") if ffmpeg else None)
                if name == "ffmpeg"
                else real_which(name, *args, **kwargs)
            ),
        )

    def test_missing_ffmpeg_does_not_block_service_dashboard_or_readiness(
        self,
        monkeypatch,
    ) -> None:
        """A running install with no video tools is degraded, not broken."""

        self._force_ready_host(monkeypatch, ffmpeg=False)

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        # The service and the dashboard assert their own reality, not ffmpeg's.
        assert lanes["service"].ready is True
        assert lanes["service"].status == "ready"
        assert lanes["dashboard"].ready is True
        assert lanes["dashboard"].status == "ready"
        # An absent optional capability does not make the install broken.
        assert summary.ready is True
        # The ffmpeg lane still tells the truth and is still distinguishable.
        assert lanes["ffmpeg"].ready is False
        assert lanes["ffmpeg"].status == "unavailable"
        assert "FFmpeg" in lanes["ffmpeg"].next_step
        # ...and it must not promise a repair action that cannot deliver.
        assert "repair" not in lanes["ffmpeg"].next_step.lower()
        # "degraded" and "broken" must not render identically: an unready lane
        # is present even though the summary reports ready.
        assert any(not lane.ready for lane in summary.lanes)
        # The GUI keys its "Repair this step" affordance off error/blocked
        # (apps/installer/src/App.tsx canRepairLane), so neither may appear.
        assert lanes["ffmpeg"].status not in {"blocked", "error", "failed"}

    def test_broken_required_lane_still_reports_not_ready(
        self,
        monkeypatch,
    ) -> None:
        """Readiness over required lanes must still fail closed."""

        self._force_ready_host(monkeypatch, ffmpeg=False)
        blocked_storage = service.durable_storage_status().model_copy(
            update={"status": "not_configured"}
        )
        monkeypatch.setattr(service, "durable_storage_status", lambda: blocked_storage)

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert summary.ready is False
        assert lanes["storage"].ready is False
        assert lanes["service"].ready is False

    def test_present_ffmpeg_keeps_the_video_lane_green(
        self,
        monkeypatch,
    ) -> None:
        self._force_ready_host(monkeypatch, ffmpeg=True)

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert lanes["ffmpeg"].ready is True
        assert lanes["ffmpeg"].status == "ready"
        assert summary.ready is True

    # ------------------------------------------------------------------
    # Native Windows station platform lane
    #
    # This used to be decided by ``_detected_bootstrap_plan``, which
    # hard-coded ``ubuntu``/``ubuntu_wsl2`` to False on a Windows host, and
    # ``PlatformBootstrapPlan`` rejected a native Windows runtime outright --
    # so the platform lane could never clear on the native product, and it
    # dragged ``service``, ``dashboard``, and the summary's ``ready`` flag
    # down with it forever. Windows is now decided entirely by this
    # process's own native-station activation signals, never by that
    # generic multi-OS plan (which now only covers Linux/macOS).
    # ------------------------------------------------------------------

    @staticmethod
    def _force_native_station(
        monkeypatch,
        tmp_path,
        *,
        activated: bool,
        storage_ready: bool = True,
        orphan_manifest: bool = False,
        real_storage: bool = False,
    ) -> None:
        """Put the summary on a NATIVE Windows station's control plane.

        Reproduces both signals the product actually sets: the installed
        layout ``<install_root>\\runtime\\python.exe`` (present from first
        boot) and, once the supervisor's ``station_environment_for_python``
        overlay succeeds, ``CIVICCAST_NATIVE_STATION=1`` plus the
        station-set manifest path.
        """

        monkeypatch.setattr(service.platform, "system", lambda: "Windows")
        runtime_dir = tmp_path / "install" / "runtime"
        runtime_dir.mkdir(parents=True)
        embedded_python = runtime_dir / "python.exe"
        embedded_python.write_text("", encoding="utf-8")
        monkeypatch.setattr(service.sys, "executable", str(embedded_python))
        monkeypatch.delenv("CIVICCAST_NATIVE_STATION", raising=False)
        monkeypatch.delenv("CIVICCAST_NATIVE_STATION_MANIFEST", raising=False)
        manifest = tmp_path / "install" / "station-set.json"
        if activated or orphan_manifest:
            monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
            monkeypatch.setenv("CIVICCAST_NATIVE_STATION_MANIFEST", str(manifest))
        if activated and not orphan_manifest:
            manifest.write_text("{}", encoding="utf-8")
        if real_storage:
            # Leave the real durable_storage_status in place so the whole chain
            # -- DATABASE_URL -> bounded probe -> lane -> summary.ready -- runs.
            return
        storage = service.durable_storage_status().model_copy(
            update={
                "status": "ready" if storage_ready else "not_configured",
                "migrations_applied": storage_ready,
            }
        )
        monkeypatch.setattr(service, "durable_storage_status", lambda: storage)

    def test_activated_native_station_is_not_permanently_blocked_by_wsl_tooling(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """A healthy native install can reach ready. It could not before."""

        self._force_native_station(monkeypatch, tmp_path, activated=True)

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert lanes["platform"].ready is True
        assert lanes["platform"].status == "ready"
        # The lanes the platform lane used to drag down with it.
        assert lanes["service"].ready is True
        assert lanes["dashboard"].ready is True
        assert summary.ready is True
        # A native operator must not be sent to a WSL helper that this
        # product does not use.
        native_next_step = lanes["platform"].next_step.lower()
        assert "helper" not in native_next_step
        assert "wsl" not in native_next_step
        assert "ubuntu" not in native_next_step

    def test_native_station_before_activation_reports_not_ready(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """Installed but not activated is a real blocker, and must stay red.

        The supervisor starts the control plane with NO station env at all in
        this state (``NativeStationNotActivatedError`` ->
        "pre-activation mode"), so the lane sees exactly what it sees here.
        """

        self._force_native_station(monkeypatch, tmp_path, activated=False)

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert lanes["platform"].ready is False
        assert lanes["platform"].status == "blocked"
        assert lanes["service"].ready is False
        assert lanes["dashboard"].ready is False
        assert summary.ready is False
        assert "not activated yet" in lanes["platform"].next_step
        assert "helper" not in lanes["platform"].next_step.lower()

    def test_native_station_env_without_its_manifest_fails_closed(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """A stale exported variable alone must never turn the lane green."""

        self._force_native_station(
            monkeypatch,
            tmp_path,
            activated=True,
            orphan_manifest=True,
        )

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert lanes["platform"].ready is False
        assert lanes["platform"].status == "blocked"
        assert summary.ready is False

    def test_native_station_with_unprepared_storage_still_reports_not_ready(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """The fix must not become an unconditional green on native."""

        self._force_native_station(
            monkeypatch,
            tmp_path,
            activated=True,
            storage_ready=False,
        )

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert lanes["platform"].ready is True
        assert lanes["storage"].ready is False
        assert lanes["service"].ready is False
        assert lanes["dashboard"].ready is False
        assert summary.ready is False

    # ------------------------------------------------------------------
    # A native station's readiness must be EARNED by the database, not
    # inferred from DATABASE_URL being set.
    #
    # On native, DATABASE_URL is ALWAYS set (the supervisor hydrates it from
    # HKLM), and durable_storage_status() used to answer status="ready",
    # migrations_applied=True for any non-managed DATABASE_URL with no
    # connection attempt and no schema check. Every required lane in the
    # summary was a static env/filesystem inference, so a station whose
    # database was stopped -- or whose migrations had never run -- reported
    # ready=True with storage, service, and dashboard all green.
    # ------------------------------------------------------------------

    @staticmethod
    def _native_station_with_database(monkeypatch, tmp_path, outcome) -> None:
        """Activated native station whose external database answers ``outcome``.

        ``outcome`` is either an alembic revision string (or None) that the
        database reports, or an exception the connect raises. Injected at
        ``civiccast.schema_check.read_db_revision`` -- the one real connect --
        so no live Postgres is required while the bounded execution, the
        missing-database classification, and the alembic-head comparison all
        still run for real.
        """

        from civiccast import schema_check
        from civiccast.installer import storage as installer_storage

        TestInstallerApiContract._force_native_station(
            monkeypatch, tmp_path, activated=True, real_storage=True
        )
        monkeypatch.setenv("DATABASE_URL", "postgresql://civiccast:pw@10.0.0.9:5432/civiccast")
        monkeypatch.setenv("CIVICCAST_MANAGED_STORAGE_DIR", str(tmp_path / "managed"))
        installer_storage.reset_external_database_probe_cache()

        def fake_read_db_revision(database_url: str) -> str | None:
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        monkeypatch.setattr(schema_check, "read_db_revision", fake_read_db_revision)

    def test_native_station_with_an_unreachable_database_is_not_ready(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """The reproduced defect: green readiness on a dead station."""

        from sqlalchemy.exc import OperationalError

        self._native_station_with_database(
            monkeypatch,
            tmp_path,
            OperationalError("connect", {}, ConnectionRefusedError("refused")),
        )

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert summary.ready is False
        assert lanes["storage"].ready is False
        assert lanes["secrets"].ready is False
        assert lanes["service"].ready is False
        assert lanes["dashboard"].ready is False
        # The platform lane is genuinely fine -- the station IS activated. The
        # summary must fail on the lane that is actually broken.
        assert lanes["platform"].ready is True
        # And it must say which failure this is, not "Choose Prepare storage"
        # (an action the setup routes provably no-op when DATABASE_URL is set).
        assert "could not reach its database" in lanes["storage"].next_step
        assert "Prepare storage" not in lanes["storage"].next_step

    def test_native_station_with_a_schema_behind_database_is_not_ready(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """Auth works, the token works, migrations are missing. Still not ready.

        <installer-path-audit MA-06> The revision is now a REAL ancestor from
        this build's own migration graph. ``"0001_an_ancestor_revision"`` was
        never in the graph, which is the "a newer build migrated this database"
        case, not the "behind" case this test is named for.
        """

        from civiccast import schema_check

        head = schema_check.expected_migration_head()
        ancestor = sorted(schema_check.known_revisions() - {head})[0]
        self._native_station_with_database(monkeypatch, tmp_path, ancestor)

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert summary.ready is False
        assert lanes["storage"].ready is False
        assert lanes["service"].ready is False
        assert lanes["dashboard"].ready is False
        assert "older version of CivicCast" in lanes["storage"].next_step
        # Distinguishable from unreachable on screen, not one shared red.
        assert "could not reach" not in lanes["storage"].next_step

    def test_native_station_with_a_schema_ahead_database_is_not_ready(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """<installer-path-audit MA-06> A NEWER build migrated this database.

        The operator must not be told to "bring the database up to date": on
        an ahead database ``alembic upgrade head`` cannot find the revision it
        is stamped with, so that instruction fails.
        """

        self._native_station_with_database(
            monkeypatch, tmp_path, "9999_a_revision_from_a_future_build"
        )

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert summary.ready is False
        assert lanes["storage"].ready is False
        assert "NEWER version of CivicCast" in lanes["storage"].next_step
        assert "older version of CivicCast" not in lanes["storage"].next_step
        assert "could not reach" not in lanes["storage"].next_step

    def test_native_station_with_a_current_database_reaches_ready(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """The fix must not become an unconditional red, either."""

        from civiccast.schema_check import expected_migration_head

        self._native_station_with_database(monkeypatch, tmp_path, expected_migration_head())

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert lanes["storage"].ready is True
        assert lanes["storage"].next_step == "Local database and upload storage are ready."
        assert lanes["service"].ready is True
        assert lanes["dashboard"].ready is True
        assert summary.ready is True

    def test_native_station_with_a_malformed_database_url_is_not_ready(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        self._native_station_with_database(monkeypatch, tmp_path, None)
        monkeypatch.setenv("DATABASE_URL", "this is not a database address")

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert summary.ready is False
        assert lanes["storage"].ready is False
        assert "not in a form CivicCast understands" in lanes["storage"].next_step

    # ------------------------------------------------------------------
    # summary.platform must name the DEPLOYMENT: apps/installer/src/lane-
    # affordances.ts's isWindowsPlatform gates "Open installer log" on it
    # being exactly "windows-native".
    # ------------------------------------------------------------------

    def test_native_station_reports_a_native_platform(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        """Reporting "windows-wsl2" here armed the WSL bootstrap on native.

        A PRE-ACTIVATION native station is the exact venue shape of a fresh
        install: the platform lane is "blocked" while activation finishes.
        That combination -- platform "windows-wsl2" + lane id "platform" +
        status "blocked" -- is precisely what App.tsx's isWslBootstrapLane
        keys on, so the first screen offered "Set up Windows helper" (which
        runs headless-bootstrap.ps1's apt-get install) directly beneath the
        native copy telling the operator to let the installer finish.
        """

        self._force_native_station(monkeypatch, tmp_path, activated=False)

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert summary.platform == "windows-native"
        assert lanes["platform"].status == "blocked"
        # The GUI gates, restated here so the contract and the UI cannot drift:
        # both require platform == "windows-wsl2" exactly.
        assert summary.platform != "windows-wsl2"

    def test_activated_native_station_also_reports_a_native_platform(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        self._force_native_station(monkeypatch, tmp_path, activated=True)

        assert service.build_installer_summary().platform == "windows-native"

    def test_windows_host_without_a_native_install_still_reports_native_platform(
        self,
        monkeypatch,
    ) -> None:
        """A Windows host with neither native signal present (no station
        env, interpreter not the installed ``<root>\\runtime`` one) is an
        UNACTIVATED native station, not a different deployment -- there is
        no other Windows deployment left to fall back to. It must report
        honestly as blocked, never claim readiness, and never mention a
        Windows helper this product does not have."""

        monkeypatch.delenv("CIVICCAST_NATIVE_STATION", raising=False)
        monkeypatch.delenv("CIVICCAST_NATIVE_STATION_MANIFEST", raising=False)
        monkeypatch.setattr(service.platform, "system", lambda: "Windows")

        summary = service.build_installer_summary()
        lanes = {lane.id: lane for lane in summary.lanes}

        assert summary.platform == "windows-native"
        assert lanes["platform"].ready is False
        assert lanes["platform"].status == "blocked"
        assert "helper" not in lanes["platform"].next_step.lower()
        assert summary.ready is False
