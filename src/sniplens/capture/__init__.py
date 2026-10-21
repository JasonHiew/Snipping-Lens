from dataclasses import dataclass

from PySide6.QtGui import QImage

from sniplens import paths


@dataclass
class Success:
    image: QImage


@dataclass
class Cancelled:
    reason: str = ""


@dataclass
class PermissionDenied:
    message: str


@dataclass
class BackendUnavailable:
    message: str


@dataclass
class CaptureFailed:
    message: str


def create_capture_service(app):
    """The single region-capture entry point; everything above this layer is
    unaware of Windows, macOS, Wayland, X11 or portals."""
    if paths.IS_WINDOWS:
        from sniplens.capture.windows_snip import WindowsSnipCapture

        return WindowsSnipCapture()
    if paths.IS_MAC:
        from sniplens.capture.mac_capture import MacRegionCapture

        return MacRegionCapture()
    from sniplens.capture.linux_capture import LinuxRegionCapture

    return LinuxRegionCapture(app)
