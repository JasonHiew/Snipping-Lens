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


def test_screen_recording_is_requested_once(monkeypatch):
    """A grant only applies after a relaunch, so asking again on every snip
    reopens System Settings each time."""
    import sys
    import types

    from sniplens.capture import mac_capture

    requests = []
    quartz = types.SimpleNamespace(
        CGPreflightScreenCaptureAccess=lambda: False,
        CGRequestScreenCaptureAccess=lambda: requests.append(1),
    )
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setattr(mac_capture, "_access_requested", False)
    assert not mac_capture._screen_capture_allowed()
    assert not mac_capture._screen_capture_allowed()
    assert requests == [1]


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
    base_python = tmp_path / "python" / "bin" / "python3.11"
    base_python.parent.mkdir(parents=True)
    base_python.write_bytes(b"interpreter")
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(base_python)
    monkeypatch.setattr(paths, "VENV_DIR", str(venv))
    monkeypatch.setattr(
        os.path, "expanduser", lambda p: p.replace("~", str(home), 1) if p.startswith("~") else p
    )
    import sniplens.shortcuts as shortcuts

    shortcuts = importlib.reload(shortcuts)
    sips_calls = []
    monkeypatch.setattr(
        shortcuts.subprocess,
        "run",
        lambda args, **kwargs: sips_calls.append(args) or type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})(),
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
    site_packages = contents / "lib" / shortcuts.PYTHON_LIB / "site-packages"
    # only a .pth: Python would cache a module's bytecode inside the bundle
    assert [p.name for p in site_packages.iterdir()] == ["sniplens.pth"]
    boot = (site_packages / "sniplens.pth").read_text().splitlines()[1]
    assert boot.startswith("import ") and "len(sys.orig_argv) == 1" in boot
    compile(boot, "sniplens.pth", "exec")
    assert "setup_mac.sh" in shortcuts.BUNDLE_BOOT and "--hidden" in shortcuts.BUNDLE_BOOT
    assert repr(paths.MAIN_SCRIPT) in shortcuts.BUNDLE_BOOT
    assert sips_calls and sips_calls[0][0] == "/usr/bin/sips"


def test_app_bundle_executable_is_a_copy_of_python(mac_shortcuts, tmp_path):
    """macOS only shows the menu bar icon and asks for permissions for the
    process it launched, so the bundle must not exec into another binary."""
    shortcuts, home, _ = mac_shortcuts
    shortcuts.ensure_app_bundle()
    contents = home / "Applications" / "Snipping Lens.app" / "Contents"
    assert (contents / "MacOS" / "snipping-lens").read_bytes() == b"interpreter"
    cfg = (contents / "pyvenv.cfg").read_text()
    assert f"home = {tmp_path / 'python' / 'bin'}" in cfg
    pth = contents / "lib" / shortcuts.PYTHON_LIB / "site-packages" / "sniplens.pth"
    assert pth.read_text().splitlines()[0] == str(tmp_path / "venv" / "lib" / shortcuts.PYTHON_LIB / "site-packages")
    # signing rewrites the copy; that alone must not bring the original back
    (contents / "MacOS" / "snipping-lens").write_bytes(b"signed interpreter")
    shortcuts.ensure_app_bundle()
    assert (contents / "MacOS" / "snipping-lens").read_bytes() == b"signed interpreter"
    (tmp_path / "python" / "bin" / "python3.11").write_bytes(b"updated interpreter")
    shortcuts.ensure_app_bundle()
    assert (contents / "MacOS" / "snipping-lens").read_bytes() == b"updated interpreter"


IDENTITIES = b"""Policy: Code Signing
  Matching identities
  1) 9FB2D230CF7D65DDB33292A94678E3A80FAECF72 "Apple Development: someone@example.com (TEAM)" (CSSMERR_TP_CERT_EXPIRED)
  2) 1111111111111111111111111111111111111111 "Snipping Lens Signing" (CSSMERR_TP_NOT_TRUSTED)
     2 identities found
"""


class FakeCodesign:
    """Stands in for codesign and security: `valid` is whether the bundle's
    signature verifies, `signer` the certificate it was last signed with."""

    def __init__(self, identities=b"", valid=True, signer="-"):
        self.identities = identities
        self.valid = valid
        self.signer = signer
        self.signed_with = []
        self.resets = []

    def __call__(self, args, **kwargs):
        stdout = stderr = b""
        returncode = 0
        if args[0] == "/usr/bin/security":
            stdout = self.identities
        elif args[0] == "/usr/bin/tccutil":
            self.resets.append(args[2])
        elif args[1:3] == ["-d", "-r-"]:
            # an ad-hoc requirement names the exact build, a certificate's does not
            build = f"cdhash of build {len(self.signed_with)}" if self.signer == "-" else self.signer
            stdout = f"designated => {build}\n".encode()
        elif args[1] == "--verify":
            returncode = 0 if self.valid else 1
        elif args[1] == "-dvv":
            stderr = b"Signature=adhoc\n" if self.signer == "-" else f"Authority={self.signer}\n".encode()
        elif args[1] == "--force":
            identity = args[args.index("--sign") + 1]
            self.signed_with.append(identity)
            self.valid = True
            self.signer = "-" if identity == "-" else "Snipping Lens Signing"
        return type("R", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


def test_app_bundle_is_signed_ad_hoc_only_when_its_signature_breaks(mac_shortcuts, monkeypatch):
    shortcuts, _, _ = mac_shortcuts
    fake = FakeCodesign()
    monkeypatch.setattr(shortcuts.subprocess, "run", fake)
    shortcuts.ensure_app_bundle()
    assert fake.signed_with == []
    fake.valid = False
    shortcuts.ensure_app_bundle()
    assert fake.signed_with == ["-"]
    # a rebuilt ad-hoc bundle is a new app to macOS, so its old grants are void
    assert fake.resets == ["ScreenCapture", "ListenEvent", "Accessibility"]


def test_app_bundle_moves_to_the_signing_certificate_once(mac_shortcuts, monkeypatch):
    """A certificate keeps the permissions macOS granted across re-signs, so
    an ad-hoc bundle is re-signed with one as soon as it is in the keychain."""
    shortcuts, _, _ = mac_shortcuts
    fake = FakeCodesign(identities=IDENTITIES)
    monkeypatch.setattr(shortcuts.subprocess, "run", fake)
    shortcuts.ensure_app_bundle()
    shortcuts.ensure_app_bundle()
    assert fake.signed_with == ["1111111111111111111111111111111111111111"]
    # the grants made to the ad-hoc build are void; cleared once, not twice
    assert fake.resets == ["ScreenCapture", "ListenEvent", "Accessibility"]


def test_signing_identity_choice(mac_shortcuts, monkeypatch):
    shortcuts, _, _ = mac_shortcuts
    only_expired = IDENTITIES.replace(b"Snipping Lens Signing", b"Someone Else")
    monkeypatch.setattr(shortcuts.subprocess, "run", FakeCodesign(identities=only_expired))
    assert shortcuts._signing_identity()[0] == "-"
    valid_apple = b'  1) 2222222222222222222222222222222222222222 "Apple Development: someone@example.com (TEAM)"\n'
    monkeypatch.setattr(shortcuts.subprocess, "run", FakeCodesign(identities=valid_apple))
    assert shortcuts._signing_identity()[0] == "2222222222222222222222222222222222222222"


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


def test_hotkeys_ask_for_input_monitoring(monkeypatch, caplog):
    """pynput's listener only listens, so Input Monitoring is the permission
    it needs; without it the hotkeys silently never fire."""
    import sys
    import types

    from sniplens import macos

    requests = []
    quartz = types.SimpleNamespace(
        CGPreflightListenEventAccess=lambda: False,
        CGRequestListenEventAccess=lambda: requests.append(1) or False,
    )
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    opened = []
    monkeypatch.setattr(macos, "_open_settings", opened.append)
    macos.warn_if_hotkeys_blocked()
    assert requests == [1]
    assert opened == [macos.INPUT_MONITORING_SETTINGS]
    assert "Input Monitoring" in caplog.text
