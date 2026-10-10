import os
import sys
import json
import subprocess
import psutil
import logging
import atexit
import uuid
import signal
import time

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction, QActionGroup
from PySide6.QtCore import QObject, QPoint, QTimer

EXE_DIR = os.path.dirname(
    os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)
)
EXIT_WATCHDOG = os.path.join(EXE_DIR, ".exit_watchdog")
SETTINGS_PATH = os.path.abspath(os.path.join(EXE_DIR, "..", "config", "settings.json"))
LOCKFILE_APP = os.path.join(EXE_DIR, ".flet_config.lock")
LOCKFILE = os.path.join(EXE_DIR, ".sniplens.lock")
LOG_FILE = os.path.abspath(os.path.join(EXE_DIR, "..", "logs", "sniplens.log"))


def singleton_lock():
    if os.path.exists(LOCKFILE):
        try:
            with open(LOCKFILE, "r") as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                if "python" in proc.name().lower() and any(
                    "sniplens.py" in part for part in proc.cmdline()
                ):
                    print(
                        "sniplens.py is already running (PID {}). Exiting.".format(pid)
                    )
                    sys.exit(0)
        except Exception:
            pass
        try:
            os.remove(LOCKFILE)
        except Exception:
            pass
    with open(LOCKFILE, "w") as f:
        f.write(str(os.getpid()))


def remove_lock():
    try:
        if os.path.exists(LOCKFILE):
            os.remove(LOCKFILE)
            logging.info("sniplens.py lockfile removed on exit.")
    except Exception:
        pass


def signal_handler(signum, frame):
    """Handle termination signals gracefully"""
    logging.info(f"Received signal {signum}, cleaning up...")
    remove_lock()
    sys.exit(0)


singleton_lock()
atexit.register(remove_lock)

# Register signal handlers for proper cleanup
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

DEFAULT_SETTINGS_WRAPPED = {
    "tray_ui_enabled": {"value": True, "description": "Enable or disable the tray UI"},
    "tray_status": {"value": 2, "description": "0=Pause, 1=Tray Only, 2=Always On"},
    "alternate_hotkey": {
        "value": "",
        "description": "Alternate hotkey for Windows Snipping Tool (e.g., 'ctrl+shift+s')",
    },
    "auto_upload_enabled": {
        "value": True,
        "description": "Automatically upload snips and open Google Lens",
    },
}

DEFAULT_SETTINGS = {k: v["value"] for k, v in DEFAULT_SETTINGS_WRAPPED.items()}

DEFAULT_CLIPBOARD_SITES = [
    {
        "id": "jpdb",
        "name": "JPDB",
        "url": "https://jpdb.io/search?q=<search_term>",
        "enabled": True,
    }
]


def get_clipboard_sites():
    try:
        with open(SETTINGS_PATH, "r") as f:
            raw = json.load(f)
    except Exception:
        return DEFAULT_CLIPBOARD_SITES
    val = raw.get("clipboard_sites")
    sites = val["value"] if isinstance(val, dict) and "value" in val else val
    return sites if isinstance(sites, list) and sites else DEFAULT_CLIPBOARD_SITES


def get_default_clipboard_site_id():
    try:
        with open(SETTINGS_PATH, "r") as f:
            raw = json.load(f)
    except Exception:
        return DEFAULT_CLIPBOARD_SITES[0]["id"]
    val = raw.get("default_clipboard_site_id")
    default_id = val["value"] if isinstance(val, dict) and "value" in val else val
    return default_id or DEFAULT_CLIPBOARD_SITES[0]["id"]


def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def extract_values(settings_obj):
    out = {}
    for key, entry in settings_obj.items():
        if isinstance(entry, dict) and "value" in entry:
            val = entry["value"]
            if key == "tray_status":
                try:
                    val = int(val)
                except Exception:
                    val = 1
            out[key] = val
    return out


def validate_settings(raw):
    for key in ["tray_ui_enabled", "tray_status", "alternate_hotkey"]:
        if key not in raw:
            raise ValueError(f"Missing key: {key}")
        value_entry = raw[key]
        if not isinstance(value_entry, dict) or "value" not in value_entry:
            raise ValueError(f"Invalid format for key: {key}")
        value = value_entry["value"]
        if key == "tray_ui_enabled":
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
        elif key == "tray_status":
            if not (
                isinstance(value, int) or (isinstance(value, str) and value.isdigit())
            ):
                raise ValueError(f"{key} must be an integer or digit-string")
        elif key == "alternate_hotkey":
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")


def load_settings():
    try:
        with open(SETTINGS_PATH, "r") as f:
            raw = json.load(f)
        validate_settings(raw)
        settings = extract_values(raw)
        return {
            key: settings.get(key, DEFAULT_SETTINGS[key]) for key in DEFAULT_SETTINGS
        }
    except Exception:
        with open(SETTINGS_PATH, "w") as f:
            json.dump(DEFAULT_SETTINGS_WRAPPED, f, indent=4)
        python = sys.executable
        os.execl(python, python, *sys.argv)


def update_settings(updates: dict):
    """Safely update and merge settings, then save to disk."""
    try:
        try:
            with open(SETTINGS_PATH, "r") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
        raw.update(updates)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(raw, f, indent=4)
    except Exception as e:
        logging.error("Failed to update settings: %s", e)


def is_watchdog_running():
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmdline = proc.info["cmdline"]
            if cmdline and any("tray_watchdog.py" in part for part in cmdline):
                return True
        except Exception:
            continue
    return False


def open_flet_window():
    if os.path.exists(LOCKFILE_APP):
        try:
            with open(LOCKFILE_APP, "r") as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                if "python" in proc.name().lower():
                    logging.info("Application window already running.")
                    return
        except Exception:
            pass
        try:
            os.remove(LOCKFILE_APP)
        except Exception:
            pass
    logging.info("Launching Snipping Lens main window.")
    subprocess.Popen([sys.executable, os.path.join(EXE_DIR, "config_window.py")])


class TrayApp(QObject):
    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.settings = load_settings()

        icon_path = os.path.abspath(
            os.path.join(EXE_DIR, "..", "assets", "sniplens.png")
        )
        self.tray_icon = QSystemTrayIcon(QIcon(resource_path(icon_path)))
        self.tray_icon.setToolTip("Snipping Lens")
        self.tray_icon.activated.connect(self.icon_clicked)

        self.menu = QMenu()
        self.menu.setStyleSheet(
            """
            QMenu {
                background-color: #333333;
                color: white;
                border: 1px solid #555;
                padding: 5px;
            }
            QMenu::item {
                padding: 5px 20px;
                background-color: transparent;
            }
            QMenu::item:selected {
                background-color: #555555;
            }
            QMenu::item[text="Exit"] {
                text-align: center;
                color: #ff6b6b;
                font-weight: bold;
            }
        """
        )
        self.config_action = QAction("Open App")
        self.config_action.triggered.connect(self.open_config)
        self.menu.addAction(self.config_action)
        self.auto_upload_action = QAction("Auto Upload to Google Lens")
        self.auto_upload_action.setCheckable(True)
        self.auto_upload_action.setChecked(
            bool(self.settings.get("auto_upload_enabled", True))
        )
        self.auto_upload_action.toggled.connect(self.toggle_auto_upload)
        self.menu.addAction(self.auto_upload_action)
        self.sites_menu = QMenu("Default Search Site")
        self.sites_menu.aboutToShow.connect(self.populate_sites_menu)
        self.menu.addMenu(self.sites_menu)
        self.menu.addSeparator()
        self.quit_action = QAction("Exit")
        self.quit_action.triggered.connect(self.exit_app)
        self.menu.addAction(self.quit_action)
        self.tray_icon.setContextMenu(self.menu)

        self.tray_ui_enabled = self.settings.get("tray_ui_enabled", True)
        if self.tray_ui_enabled:
            self.tray_icon.show()
            logging.info("Tray icon shown.")
        else:
            self.tray_icon.hide()
            logging.info("Tray icon hidden.")

        self.last_tray_click_pos = QPoint(0, 0)

        # The watchdog does all clipboard handling; if it dies (e.g. a native
        # crash) the tray keeps running but snips are silently ignored.
        self._watchdog_missing_checks = 0
        self._watchdog_restart_times = []
        self._watchdog_gave_up = False
        self.watchdog_timer = QTimer()
        self.watchdog_timer.setInterval(5000)
        self.watchdog_timer.timeout.connect(self.check_watchdog)
        self.watchdog_timer.start()

    def check_watchdog(self):
        if os.path.exists(EXIT_WATCHDOG) or is_watchdog_running():
            self._watchdog_missing_checks = 0
            return
        # Require two consecutive misses so a watchdog that is mid-restart
        # isn't launched twice.
        self._watchdog_missing_checks += 1
        if self._watchdog_missing_checks < 2:
            return
        self._watchdog_missing_checks = 0

        now = time.time()
        self._watchdog_restart_times = [
            t for t in self._watchdog_restart_times if now - t < 600
        ]
        if len(self._watchdog_restart_times) >= 5:
            if not self._watchdog_gave_up:
                logging.error(
                    "[Tray] Watchdog crashed 5 times in 10 minutes; not restarting it again for now."
                )
                self._watchdog_gave_up = True
            return
        self._watchdog_gave_up = False
        self._watchdog_restart_times.append(now)

        logging.warning("[Tray] Watchdog is not running; restarting it.")
        try:
            subprocess.Popen(
                [sys.executable, os.path.join(EXE_DIR, "tray_watchdog.py")],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            logging.error(f"[Tray] Failed to restart watchdog: {e}")

    def icon_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            try:
                logging.info("Tray left-clicked: preparing for tray-based snip.")
                token = str(uuid.uuid4())
                update_settings({"tray_snip_token": token})
                logging.info(f"Generated snip token: {token}")

                logging.info("Launching Snipping Tool via ms-screenclip.")
                subprocess.Popen(["explorer.exe", "ms-screenclip:"])
            except Exception as e:
                logging.error(f"Failed to launch Snipping Tool: {e}")

    def open_config(self):
        open_flet_window()
        logging.info("Launched Snipping Lens main window.")

    def toggle_auto_upload(self, checked):
        self.settings["auto_upload_enabled"] = checked
        update_settings(
            {
                "auto_upload_enabled": {
                    "value": checked,
                    "description": "Automatically upload snips and open Google Lens",
                }
            }
        )
        logging.info(
            f"Auto upload to Google Lens {'enabled' if checked else 'disabled'} via tray menu."
        )

    def populate_sites_menu(self):
        self.sites_menu.clear()
        sites = get_clipboard_sites()
        current_default = get_default_clipboard_site_id()

        enabled_sites = [s for s in sites if s.get("enabled", True)]
        if not enabled_sites:
            empty_action = QAction("No sites configured")
            empty_action.setEnabled(False)
            self.sites_menu.addAction(empty_action)
            return

        group = QActionGroup(self.sites_menu)
        group.setExclusive(True)
        actions = []
        for site in enabled_sites:
            action = QAction(site.get("name") or site.get("url", ""))
            action.setCheckable(True)
            action.setChecked(site["id"] == current_default)
            action.triggered.connect(
                lambda checked, sid=site["id"]: self.set_default_site(sid)
            )
            group.addAction(action)
            self.sites_menu.addAction(action)
            actions.append(action)

        # Keep references alive while the submenu is open; QMenu.clear() only
        # deletes the underlying C++ objects, Python refs would else be collected.
        self._sites_action_group = group
        self._sites_actions = actions

    def set_default_site(self, site_id):
        update_settings(
            {
                "default_clipboard_site_id": {
                    "value": site_id,
                    "description": "ID of the site opened automatically when clipboard text changes after a Lens search.",
                }
            }
        )
        logging.info(f"Default clipboard search site set to: {site_id}")

    def exit_app(self):
        try:
            with open(SETTINGS_PATH, "r") as f:
                raw = json.load(f)
            if "tray_ui_enabled" in raw:
                if isinstance(raw["tray_ui_enabled"], dict):
                    raw["tray_ui_enabled"]["value"] = False
                else:
                    raw["tray_ui_enabled"] = False
            else:
                raw["tray_ui_enabled"] = {
                    "value": False,
                    "description": "Enable or disable the tray UI",
                }
            with open(SETTINGS_PATH, "w") as f:
                json.dump(raw, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to set tray_ui_enabled to False on exit: {e}")

        # Signal watchdog to exit
        with open(EXIT_WATCHDOG, "w") as f:
            f.write("exit")

        self.tray_icon.hide()
        logging.info("Tray app exited by user.")

        # Clean up lockfile before exit
        remove_lock()
        os._exit(0)

    def run(self):
        try:
            self.app.exec()
        finally:
            remove_lock()


if __name__ == "__main__":
    TrayApp().run()
