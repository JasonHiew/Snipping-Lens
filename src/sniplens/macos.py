import logging


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


def warn_if_hotkeys_blocked():
    """pynput's listener gets no key events, and says nothing, until the app is
    granted Accessibility access."""
    try:
        from ApplicationServices import AXIsProcessTrusted
    except ImportError:
        return
    if not AXIsProcessTrusted():
        logging.warning(
            "[Hotkey] Hotkeys need the Accessibility permission. Enable Snipping Lens "
            "(or the app that launched it, e.g. Terminal) in System Settings > Privacy "
            "& Security > Accessibility, then quit and reopen Snipping Lens."
        )
