"""macOS-only code exercised on any OS, with the macOS pieces faked."""

import importlib
import os
import plistlib

import pytest
from PySide6.QtGui import QGuiApplication, QImage

from sniplens import paths
from sniplens.capture import Cancelled, CaptureFailed, PermissionDenied, Success


class FakeProcess:
    def deleteLater(self):
        pass


@pytest.fixture(scope="module")
def qt_app():
    return QGuiApplication.instance() or QGuiApplication(["test", "-platform", "offscreen"])


@pytest.fixture
def capture(qt_app, monkeypatch):
    from sniplens.capture import mac_capture

    instance = mac_capture.MacRegionCapture()
    outcomes = []
    instance.completed.connect(outcomes.append)
    return mac_capture, instance, outcomes


def test_capture_reports_permission_denied(capture, monkeypatch):
    mac_capture, instance, outcomes = capture
    monkeypatch.setattr(mac_capture, "_screen_capture_allowed", lambda: False)
    instance.request_region()
    assert len(outcomes) == 1 and isinstance(outcomes[0], PermissionDenied)
    assert "Screen Recording" in outcomes[0].message


def test_capture_without_output_is_a_cancellation(capture, tmp_path):
    """screencapture exits without writing a file when the user presses Esc."""
    _, instance, outcomes = capture
    instance._process = FakeProcess()
    instance._on_finished(str(tmp_path / "missing.png"))
    assert isinstance(outcomes[0], Cancelled)
    assert instance._process is None


def test_capture_returns_the_image(capture, tmp_path):
    _, instance, outcomes = capture
    output = tmp_path / "snip.png"
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0xFF00FF)
    image.save(str(output))
    instance._process = FakeProcess()
    instance._on_finished(str(output))
    assert isinstance(outcomes[0], Success)
    assert outcomes[0].image.size() == image.size()


def test_capture_rejects_an_unreadable_image(capture, tmp_path):
    _, instance, outcomes = capture
    output = tmp_path / "snip.png"
    output.write_bytes(b"not a png")
    instance._process = FakeProcess()
    instance._on_finished(str(output))
    assert isinstance(outcomes[0], CaptureFailed)


@pytest.fixture
def mac_shortcuts(monkeypatch, tmp_path):
    """sniplens.shortcuts picks its platform at import, so reload it as macOS
    with the home folder redirected, and reload it back afterwards."""
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    monkeypatch.setattr(paths, "IS_MAC", True)
    monkeypatch.setattr(paths, "IS_LINUX", False)
    home = tmp_path / "home"
    monkeypatch.setattr(
        os.path, "expanduser", lambda p: p.replace("~", str(home), 1) if p.startswith("~") else p
    )
    import sniplens.shortcuts as shortcuts

    shortcuts = importlib.reload(shortcuts)
    sips_calls = []
    monkeypatch.setattr(
        shortcuts.subprocess,
        "run",
        lambda args, **kwargs: sips_calls.append(args) or type("R", (), {"returncode": 0, "stderr": b""})(),
    )
    yield shortcuts, home, sips_calls
    monkeypatch.undo()
    importlib.reload(shortcuts)


def test_app_bundle_is_a_menu_bar_launcher(mac_shortcuts):
    shortcuts, home, sips_calls = mac_shortcuts
    shortcuts.ensure_app_bundle()
    contents = home / "Applications" / "Snipping Lens.app" / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    assert info["LSUIElement"] is True
    assert info["CFBundleIdentifier"] == "com.snippinglens.app"
    launcher = (contents / "MacOS" / info["CFBundleExecutable"]).read_text()
    assert launcher.startswith("#!/bin/bash\n")
    assert "setup_mac.sh" in launcher and "--hidden" in launcher
    assert sips_calls and sips_calls[0][0] == "/usr/bin/sips"


def test_startup_writes_and_removes_a_launch_agent(mac_shortcuts):
    shortcuts, home, _ = mac_shortcuts
    agent = home / "Library" / "LaunchAgents" / "com.snippinglens.app.plist"
    shortcuts.set_startup(True)
    content = plistlib.loads(agent.read_bytes())
    assert content["RunAtLoad"] is True
    opener, bundle = content["ProgramArguments"]
    assert opener == "/usr/bin/open"
    assert os.path.normpath(bundle) == str(home / "Applications" / "Snipping Lens.app")
    shortcuts.set_startup(False)
    assert not agent.exists()


def test_integration_entries_skip_the_agent_when_startup_is_off(mac_shortcuts):
    shortcuts, home, _ = mac_shortcuts
    shortcuts.ensure_integration_entries(startup_enabled=False)
    assert (home / "Applications" / "Snipping Lens.app" / "Contents" / "Info.plist").exists()
    assert not (home / "Library" / "LaunchAgents").exists()
