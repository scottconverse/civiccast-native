"""Emergency presentation crosses the existing encoder graphics seam."""

from civiccast.cg.models import EmergencyOverlay
from civiccast.eas.presentation import presentation_enabled, render_presentation


def test_emergency_presentation_is_opt_in(monkeypatch):
    monkeypatch.delenv("CIVICCAST_EAS", raising=False)
    assert not presentation_enabled()
    monkeypatch.setenv("CIVICCAST_EAS", "inline")
    assert presentation_enabled()


def test_real_render_produces_alert_image(tmp_path):
    overlay = EmergencyOverlay(
        overlay_id="test",
        severity="emergency",
        title="TEST FLOOD WARNING",
        message="River Road is closed.",
        instructions="Move to higher ground.",
        cellular_fallback_enabled=False,
    )
    payload = render_presentation("overlay", overlay, tmp_path, width=640, height=360)
    assert payload["mode"] == "overlay"
    assert payload["ypos"] > 0
    assert payload["image_path"].endswith(".png")
    from pathlib import Path

    assert Path(payload["image_path"]).read_bytes().startswith(b"\x89PNG")


def test_emergency_sync_uses_windows_control_and_clears_expired_state(tmp_path, monkeypatch):
    import base64
    from types import SimpleNamespace

    from civiccast.cg.models import EmergencyOverlay
    from civiccast.egress.gst.strategy import GstPlayoutStrategy
    from civiccast.egress.models import CanonicalProfile
    from civiccast.native.supervisor.replay import ChannelReplay, Command

    monkeypatch.setenv("CIVICCAST_EAS", "inline")
    overlay = EmergencyOverlay(
        overlay_id="a1",
        severity="emergency",
        title="Flood warning",
        message="Road closed",
        instructions="Move uphill",
        cellular_fallback_enabled=False,
    )
    active = {"gov": ("overlay", overlay)}
    strategy = GstPlayoutStrategy(is_windows=True, emergency_provider=active.get)
    sent = []

    class Pipe:
        def send_and_wait(self, verb, line, **kwargs):
            sent.append((verb, line))
            return True

    strategy._pipe_channels["gov"] = Pipe()
    config = SimpleNamespace(canonical_profile=CanonicalProfile(width=640, height=360))
    assert strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert sent[0][0] == "emergency"
    payload = __import__("json").loads(base64.b64decode(sent[0][1].split()[1]))
    assert payload["mode"] == "overlay"
    assert strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert len(sent) == 1
    active.clear()
    assert strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert __import__("json").loads(base64.b64decode(sent[-1][1].split()[1])) is None
    replay = ChannelReplay(channel_id="gov")
    replay.record_sent(Command(id="show", verb="emergency", line=sent[0][1]))
    replay.record_sent(Command(id="clear", verb="emergency", line=sent[-1][1]))
    assert replay.reissue_on_reconnect()[0].line == sent[-1][1]


def test_display_admission_requires_live_channel_and_reserved_compositor():
    from types import SimpleNamespace

    from civiccast.egress.daemon import EgressDaemon

    daemon = object.__new__(EgressDaemon)
    daemon._encoder_strategy = SimpleNamespace(
        emergency_presentation_ready=lambda channel: channel == "gov"
    )
    daemon._processes = {"gov": SimpleNamespace(poll=lambda: None)}
    daemon._store = SimpleNamespace(read_state=lambda channel: SimpleNamespace(state="ON_AIR"))
    assert daemon.emergency_presentation_ready("gov")
    assert not daemon.emergency_presentation_ready("other")
    daemon._processes["gov"] = SimpleNamespace(poll=lambda: 1)
    assert not daemon.emergency_presentation_ready("gov")


def test_failed_pending_image_is_retired_before_replacement(tmp_path, monkeypatch):
    """Lost ACKs and Windows locks must not create an unbounded PNG backlog."""
    import base64
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from civiccast.egress.gst.strategy import GstPlayoutStrategy
    from civiccast.egress.models import CanonicalProfile

    monkeypatch.setenv("CIVICCAST_EAS", "inline")
    overlay = EmergencyOverlay(
        overlay_id="a",
        severity="emergency",
        title="A",
        message="A",
        instructions="A",
        cellular_fallback_enabled=False,
    )
    active = {"gov": ("overlay", overlay)}
    generated = []
    referenced = set()
    clear_ok = False
    show_ok = True
    locked = False
    original_unlink = Path.unlink

    def render(mode, item, directory, **kwargs):
        path = tmp_path / f"emergency-overlay.{len(generated)}.png"
        path.write_bytes(b"PNG")
        generated.append(path)
        return {"mode": mode, "image_path": str(path)}

    def unlink(path, *args, **kwargs):
        assert str(path) not in referenced, "attempted to delete worker-referenced image"
        if locked and path.exists():
            raise PermissionError("simulated Windows file lock")
        return original_unlink(path, *args, **kwargs)

    class Pipe:
        def send_and_wait(self, verb, line, **kwargs):
            payload = json.loads(base64.b64decode(line.split()[1]))
            if payload is None:
                if clear_ok:
                    referenced.clear()
                return clear_ok
            # The worker applied it, but its acknowledgement can be lost.
            referenced.add(payload["image_path"])
            return show_ok

    monkeypatch.setattr("civiccast.eas.presentation.render_presentation", render)
    monkeypatch.setattr(Path, "unlink", unlink)
    strategy = GstPlayoutStrategy(is_windows=True, emergency_provider=active.get)
    strategy._pipe_channels["gov"] = Pipe()
    config = SimpleNamespace(canonical_profile=CanonicalProfile(width=640, height=360))
    assert strategy.sync_emergency_overlay("gov", config, tmp_path)
    show_ok = False
    clear_ok = True
    active["gov"] = ("overlay", overlay.model_copy(update={"title": "B"}))
    assert not strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert not generated[0].exists()
    clear_ok = False
    # Returning to the last acknowledged A still needs to retire uncertain B.
    active["gov"] = ("overlay", overlay)
    assert not strategy.sync_emergency_overlay("gov", config, tmp_path)
    for index in range(10):
        active["gov"] = ("overlay", overlay.model_copy(update={"title": str(index)}))
        assert not strategy.sync_emergency_overlay("gov", config, tmp_path)
        assert len(list(tmp_path.glob("*.png"))) == 2
    allocated = len(generated)
    assert generated[1].exists()
    clear_ok = True
    locked = True
    assert not strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert not referenced
    assert len(generated) == allocated
    locked = False
    assert not strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert not generated[1].exists()
    assert len(generated) == allocated
    assert generated[-1].exists()
    assert len(list(tmp_path.glob("*.png"))) == 1


def test_failed_render_removes_partial_image(tmp_path, monkeypatch):
    from pathlib import Path

    import pytest

    def fail(args, **kwargs):
        Path(args[-1]).write_bytes(b"partial PNG")
        raise RuntimeError("encoder failed")

    monkeypatch.setattr("civiccast.eas.presentation.run_ffmpeg", fail)
    overlay = EmergencyOverlay(
        overlay_id="a",
        severity="emergency",
        title="A",
        message="A",
        instructions="A",
        cellular_fallback_enabled=False,
    )
    with pytest.raises(RuntimeError, match="encoder failed"):
        render_presentation("overlay", overlay, tmp_path, width=640, height=360)
    assert not list(tmp_path.iterdir())


def test_changed_alert_render_failure_preserves_accepted_warning(tmp_path, monkeypatch):
    import base64
    import json
    from pathlib import Path
    from types import SimpleNamespace

    import pytest

    from civiccast.egress.gst.strategy import GstPlayoutStrategy
    from civiccast.egress.models import CanonicalProfile

    monkeypatch.setenv("CIVICCAST_EAS", "inline")
    overlay = EmergencyOverlay(
        overlay_id="a",
        severity="emergency",
        title="A",
        message="A",
        instructions="A",
        cellular_fallback_enabled=False,
    )
    active = {"gov": ("overlay", overlay)}
    displayed = None
    sent = []
    fail_render = False
    clear_ok = True

    def render(mode, item, directory, **kwargs):
        if fail_render:
            raise RuntimeError("render failed")
        path = tmp_path / f"emergency-overlay.{item.title}.png"
        path.write_bytes(b"PNG")
        return {"image_path": str(path), "mode": mode}

    class Pipe:
        def send_and_wait(self, verb, line, **kwargs):
            nonlocal displayed
            payload = json.loads(base64.b64decode(line.split()[1]))
            if payload is None and not clear_ok:
                return False
            displayed = payload
            sent.append(displayed)
            return True

    monkeypatch.setattr("civiccast.eas.presentation.render_presentation", render)
    strategy = GstPlayoutStrategy(is_windows=True, emergency_provider=active.get)
    strategy._pipe_channels["gov"] = Pipe()
    config = SimpleNamespace(canonical_profile=CanonicalProfile(width=640, height=360))
    assert strategy.sync_emergency_overlay("gov", config, tmp_path)
    prior = displayed
    active["gov"] = ("overlay", overlay.model_copy(update={"title": "B"}))
    fail_render = True
    with pytest.raises(RuntimeError, match="render failed"):
        strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert displayed == prior
    assert Path(prior["image_path"]).exists()
    assert len(sent) == 1
    fail_render = False
    clear_ok = False
    assert not strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert displayed == prior
    active["gov"] = ("overlay", overlay.model_copy(update={"title": "C"}))
    fail_render = True
    with pytest.raises(RuntimeError, match="render failed"):
        strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert displayed == prior
    assert len(list(tmp_path.glob("*.png"))) == 1
    fail_render = False
    clear_ok = True
    assert strategy.sync_emergency_overlay("gov", config, tmp_path)
    assert displayed["image_path"].endswith(".C.png")
    assert not Path(prior["image_path"]).exists()
    assert len(list(tmp_path.glob("*.png"))) == 1
