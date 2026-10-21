import logging
import os
import tempfile

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtGui import QImage

from sniplens.capture import Cancelled, CaptureFailed, PermissionDenied, Success

SCREENCAPTURE = "/usr/sbin/screencapture"

SCREEN_RECORDING_HELP = (
    "Snipping Lens needs the Screen Recording permission. Enable it in System "
    "Settings > Privacy & Security > Screen & System Audio Recording, then "
    "quit and reopen Snipping Lens."
)


def _screen_capture_allowed():
    """Without the permission macOS does not fail the capture, it returns an
    image of only the wallpaper and our own windows - so check up front, and
    have macOS show its permission prompt the first time."""
    try:
        import Quartz
    except ImportError:
        logging.warning("[Snip] pyobjc Quartz unavailable, skipping the Screen Recording check.")
        return True
    if Quartz.CGPreflightScreenCaptureAccess():
        return True
    Quartz.CGRequestScreenCaptureAccess()
    return False


class MacRegionCapture(QObject):
    """Region capture through macOS's own `screencapture -i`, the same
    selection UI as Cmd+Shift+4. It runs as a QProcess so the menu bar stays
    responsive while the user drags out a region."""

    completed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._temp_dir = None

    def request_region(self):
        if self._process is not None:
            logging.info("[Snip] A capture is already in progress, ignoring the request.")
            return
        if not _screen_capture_allowed():
            logging.error("[Snip] %s", SCREEN_RECORDING_HELP)
            self.completed.emit(PermissionDenied(SCREEN_RECORDING_HELP))
            return
        self._temp_dir = tempfile.TemporaryDirectory(prefix="sniplens-")
        output = os.path.join(self._temp_dir.name, "snip.png")
        self._process = QProcess(self)
        self._process.finished.connect(lambda *_: self._on_finished(output))
        self._process.errorOccurred.connect(self._on_error)
        # -i interactive region (space toggles window mode, Esc cancels),
        # -x no shutter sound
        self._process.start(SCREENCAPTURE, ["-i", "-x", output])
        logging.info("[Snip] screencapture started, waiting for a region.")

    def stop(self):
        if self._process is not None:
            self._process.kill()
            self._process.waitForFinished(1000)
        self._reset()

    def _on_finished(self, output):
        if self._process is None:
            return
        try:
            if not os.path.exists(output) or os.path.getsize(output) == 0:
                outcome = Cancelled("selection cancelled")
            else:
                image = QImage(output)
                outcome = (
                    Success(image)
                    if not image.isNull()
                    else CaptureFailed("screencapture wrote an unreadable image")
                )
        finally:
            self._reset()
        self.completed.emit(outcome)

    def _on_error(self, error):
        if error != QProcess.ProcessError.FailedToStart or self._process is None:
            return
        self._reset()
        logging.error("[Snip] Failed to start %s.", SCREENCAPTURE)
        self.completed.emit(CaptureFailed(f"failed to start {SCREENCAPTURE}"))

    def _reset(self):
        if self._process is not None:
            self._process.deleteLater()
            self._process = None
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None
