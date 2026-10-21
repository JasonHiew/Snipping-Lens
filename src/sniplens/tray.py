import logging

from PySide6.QtGui import QActionGroup, QCursor, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from sniplens import APP_NAME, paths, theme

MENU_STYLE = f"""
QMenu {{
    background-color: {theme.MENU_BACKGROUND};
    color: {theme.MENU_TEXT};
    border: 1px solid {theme.MENU_BORDER};
    padding: 5px;
}}
QMenu::item {{
    padding: 5px 20px;
    background-color: transparent;
}}
QMenu::item:selected {{
    background-color: {theme.MENU_HIGHLIGHT};
}}
"""


class TrayController:
    """Tray icon whose actions only forward commands into the application
    controller; it holds no application logic or state of its own."""

    def __init__(self, commands, icon_path, snip_on_left_click):
        self._commands = commands
        self._snip_on_left_click = snip_on_left_click
        self.tray_icon = QSystemTrayIcon(QIcon(icon_path))
        self.tray_icon.setToolTip(APP_NAME)
        self.tray_icon.activated.connect(self._on_activated)

        self.menu = QMenu()
        self.menu.setStyleSheet(MENU_STYLE)
        if not snip_on_left_click:
            # menu-owned actions; parentless QActions would be collected by
            # Python and disappear from the menu
            snip_action = self.menu.addAction("Snip")
            snip_action.triggered.connect(
                lambda: self._commands.request_snip(from_app_trigger=True)
            )
        open_action = self.menu.addAction("Open App")
        open_action.triggered.connect(self._commands.open_config_window)
        self._auto_upload_action = self.menu.addAction("Auto Upload to Google Lens")
        self._auto_upload_action.setCheckable(True)
        self._auto_upload_action.triggered.connect(self._commands.set_auto_upload)
        self._sites_menu = self.menu.addMenu("Default Search Site")
        self._sites_menu.setStyleSheet(MENU_STYLE)
        self._sites_group = QActionGroup(self._sites_menu)
        self.menu.aboutToShow.connect(self._refresh_state)
        self.menu.addSeparator()
        quit_action = self.menu.addAction("Exit")
        quit_action.triggered.connect(self._commands.quit)
        self.tray_icon.setContextMenu(self.menu)
        # the menu's first realization pays the style polish, window creation
        # and font metrics; pay it here so the first right-click is as fast as
        # every later one instead of stalling for seconds
        self._refresh_state()
        self.menu.ensurePolished()
        self.menu.winId()
        self.menu.sizeHint()

    def show(self):
        self.tray_icon.show()
        if not self.tray_icon.isVisible():
            logging.warning("The system tray is not available on this desktop.")
        else:
            logging.info("Tray icon shown.")

    def shutdown(self):
        self.tray_icon.hide()
        self.tray_icon.deleteLater()
        self.menu.deleteLater()

    def _refresh_state(self):
        """The menu mirrors settings the config window can also change, so it
        is re-read from the controller every time the menu opens."""
        self._auto_upload_action.setChecked(self._commands.auto_upload_enabled)
        for action in self._sites_group.actions():
            self._sites_group.removeAction(action)
        self._sites_menu.clear()
        enabled = [site for site in self._commands.clipboard_sites if site["enabled"]]
        if not enabled:
            self._sites_menu.addAction("No sites configured").setEnabled(False)
            return
        for site in enabled:
            # menu-owned like the other actions, so Python never collects them
            action = self._sites_menu.addAction(site["name"])
            action.setCheckable(True)
            action.setChecked(site["id"] == self._commands.default_clipboard_site_id)
            action.triggered.connect(
                lambda _checked, site_id=site["id"]: self._commands.set_default_site(site_id)
            )
            self._sites_group.addAction(action)

    def _on_activated(self, reason):
        if reason != QSystemTrayIcon.ActivationReason.Trigger:
            return
        if self._snip_on_left_click:
            self._commands.request_snip(from_app_trigger=True)
        elif not paths.IS_MAC:
            # macOS already opens the context menu for a menu bar click; a
            # popup here would open a second copy
            self.menu.popup(QCursor.pos())
