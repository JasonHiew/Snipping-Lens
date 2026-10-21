import logging
import subprocess


def run_as_menu_bar_app():
    """Hide the Dock icon so Snipping Lens lives only in the menu bar. A Python
    process is not an app bundle with LSUIElement set, so macOS gives it a
    Dock icon until it switches itself to an accessory app."""
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    except ImportError:
        logging.warning("pyobjc AppKit unavailable, Snipping Lens keeps its Dock icon.")
        return
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


INPUT_MONITORING_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"


def _open_settings(url):
    subprocess.run(["/usr/bin/open", url], capture_output=True)


def warn_if_hotkeys_blocked():
    """pynput's listener gets no key events, and says nothing, until the app is
    granted Input Monitoring; it only listens, so it needs no Accessibility.
    Requesting the access lists Snipping Lens under Input Monitoring, ready
    to switch on."""
    try:
        from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess
    except ImportError:
        return
    if not CGPreflightListenEventAccess():
        # recent macOS only lists the app, switched off, without asking, so
        # open the page with the switch rather than leave the hotkey dead
        if not CGRequestListenEventAccess():
            _open_settings(INPUT_MONITORING_SETTINGS)
        logging.warning(
            "[Hotkey] Hotkeys need the Input Monitoring permission. Enable Snipping Lens "
            "in System Settings > Privacy & Security > Input Monitoring, then quit and "
            "reopen Snipping Lens."
        )
