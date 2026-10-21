import logging
import time
import webbrowser
from urllib.parse import quote

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication

from sniplens.settings import SEARCH_TERM_PLACEHOLDER

WATCH_SECONDS = 60
POLL_INTERVAL_MS = 500


def default_site(sites, default_id):
    """The enabled site the user picked as default, else the first enabled
    one, else None."""
    enabled = [site for site in sites if site.get("enabled", True)]
    for site in enabled:
        if site["id"] == default_id:
            return site
    return enabled[0] if enabled else None


def site_url(site, text):
    return site["url"].replace(SEARCH_TERM_PLACEHOLDER, quote(text.strip()))


class ClipboardSiteWatcher(QObject):
    """After a Lens search opens, watches for the text the user copies from
    Lens (its Copy button) and opens it in the default search site.

    The clipboard is polled on the GUI thread rather than watched through
    dataChanged, which macOS does not emit for other apps' changes. Arming
    again replaces the previous watch, so several snips followed by one Copy
    open the site once."""

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self._core = core
        self._clipboard = QGuiApplication.clipboard()
        self._timer = QTimer(self, interval=POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._baseline = None
        self._deadline = 0.0

    def arm(self):
        self._baseline = self._clipboard.text()
        self._deadline = time.monotonic() + WATCH_SECONDS
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _poll(self):
        # a timeout already queued when the watch ended must not open a site
        if not self._timer.isActive():
            return
        if time.monotonic() > self._deadline:
            self._timer.stop()
            logging.info("[ClipboardSite] Clipboard watcher timed out after %ds.", WATCH_SECONDS)
            return
        text = self._clipboard.text()
        if not text.strip() or text == self._baseline:
            return
        self._timer.stop()
        site = default_site(self._core.clipboard_sites, self._core.default_clipboard_site_id)
        if site is None:
            logging.info("[ClipboardSite] No enabled search site to open.")
            return
        url = site_url(site, text)
        logging.info("[ClipboardSite] Opening %s: %s", site["name"], url)
        webbrowser.open_new_tab(url)
