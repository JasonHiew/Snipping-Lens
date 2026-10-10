import os
import sys
import json
import atexit
import subprocess
import psutil
import time
import hashlib
import copykitten
from PIL import Image, ImageGrab
from io import BytesIO
import requests
import threading
import webbrowser
from urllib.parse import quote
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging
import signal
import faulthandler
import functools
import win32clipboard
import win32process

# Import for hotkey functionality
try:
    import pynput
    from pynput import keyboard

    HOTKEY_AVAILABLE = True
except ImportError:
    HOTKEY_AVAILABLE = False
    logging.warning("pynput not available. Alternate hotkey functionality disabled.")

EXE_DIR = os.path.dirname(
    os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)
)
EXIT_WATCHDOG = os.path.join(EXE_DIR, ".exit_watchdog")
SETTINGS_PATH = os.path.abspath(os.path.join(EXE_DIR, "..", "config", "settings.json"))
LOCKFILE = os.path.join(EXE_DIR, ".tray_watchdog.lock")
LOG_FILE = os.path.abspath(os.path.join(EXE_DIR, "..", "logs", "sniplens.log"))

# Always-On clipboard monitoring only reacts to images owned by these processes,
# so third-party tools (e.g. ShareX) writing intermediate images to the clipboard
# don't trigger an unwanted upload.
SNIP_TOOL_PROCESS_NAMES = {
    "snippingtool.exe",
    "screenclippinghost.exe",
    "sniptool.exe",
    "snipandsketch.exe",
}

DEFAULT_CLIPBOARD_SITES = [
    {
        "id": "jpdb",
        "name": "JPDB",
        "url": "https://jpdb.io/search?q=<search_term>",
        "enabled": True,
    }
]


def singleton_lock():
    if os.path.exists(LOCKFILE):
        try:
            with open(LOCKFILE, "r") as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                if "python" in proc.name().lower() and any(
                    "tray_watchdog.py" in part for part in proc.cmdline()
                ):
                    print(
                        "tray_watchdog.py is already running (PID {}). Exiting.".format(
                            pid
                        )
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
            logging.info("[Watchdog] Lockfile removed on clean exit.")
    except Exception:
        pass


def signal_handler(signum, frame):
    """Handle termination signals gracefully"""
    logging.info(f"[Watchdog] Received signal {signum}, cleaning up...")
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

# Native crashes (e.g. heap corruption) kill the process before logging runs;
# faulthandler still dumps every thread's stack to this file.
_fault_log = open(
    os.path.join(os.path.dirname(LOG_FILE), "tray_watchdog_crash.log"), "a"
)
faulthandler.enable(file=_fault_log, all_threads=True)

# The Windows clipboard is a single shared resource; copykitten, PIL and
# win32clipboard each open and close it on their own, so concurrent access from
# the monitor loop and the site watcher thread can corrupt the heap.
CLIPBOARD_LOCK = threading.Lock()


def clipboard_locked(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with CLIPBOARD_LOCK:
            return func(*args, **kwargs)

    return wrapper


# Global variable to hold the hotkey listener
hotkey_listener = None
current_hotkey = ""

try:
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "r") as f:
            raw = json.load(f)
    else:
        raw = {}
    if "tray_ui_enabled" in raw:
        if isinstance(raw["tray_ui_enabled"], dict):
            raw["tray_ui_enabled"]["value"] = True
        else:
            raw["tray_ui_enabled"] = True
    else:
        raw["tray_ui_enabled"] = {
            "value": True,
            "description": "Enable or disable the tray UI",
        }
    # Add alternate_hotkey if it doesn't exist
    if "alternate_hotkey" not in raw:
        raw["alternate_hotkey"] = {
            "value": "",
            "description": "Alternate hotkey for Windows Snipping Tool (e.g., 'ctrl+shift+s')",
        }
    with open(SETTINGS_PATH, "w") as f:
        json.dump(raw, f, indent=4)
except Exception as e:
    logging.error("Failed to set tray_ui_enabled to True on watchdog start: %s", e)


def is_tray_running():
    current_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = proc.info["pid"]
            if pid == current_pid:
                continue
            cmdline = proc.info["cmdline"]
            if cmdline and any("sniplens.py" in part for part in cmdline):
                return True
        except Exception:
            continue
    return False


def tray_setting():
    try:
        with open(SETTINGS_PATH, "r") as f:
            raw = json.load(f)
        v = raw["tray_ui_enabled"]
        if isinstance(v, dict) and "value" in v:
            return bool(v["value"])
        return bool(v)
    except Exception:
        return True


def get_alternate_hotkey():
    """Get the alternate hotkey from settings"""
    try:
        with open(SETTINGS_PATH, "r") as f:
            raw = json.load(f)
        v = raw.get("alternate_hotkey", "")
        if isinstance(v, dict) and "value" in v:
            return str(v["value"]).strip()
        return str(v).strip()
    except Exception:
        return ""


def launch_snipping_tool():
    """Launch the Windows Snipping Tool"""
    try:
        logging.info("[Hotkey] Launching Snipping Tool via alternate hotkey.")
        subprocess.Popen(["explorer.exe", "ms-screenclip:"])
    except Exception as e:
        logging.error(f"[Hotkey] Failed to launch Snipping Tool: {e}")


# Remove the old parse_hotkey function since we're not using it anymore


def setup_hotkey_listener():
    """Setup or update the hotkey listener"""
    global hotkey_listener, current_hotkey

    if not HOTKEY_AVAILABLE:
        return

    new_hotkey = get_alternate_hotkey()

    # If hotkey hasn't changed, do nothing
    if new_hotkey == current_hotkey:
        return

    # Stop existing listener if it exists
    if hotkey_listener:
        try:
            hotkey_listener.stop()
            logging.info(f"[Hotkey] Stopped listener for: {current_hotkey}")
        except Exception as e:
            logging.error(f"[Hotkey] Error stopping listener: {e}")
        hotkey_listener = None

    current_hotkey = new_hotkey

    # If new hotkey is empty, don't create a new listener
    if not new_hotkey:
        logging.info("[Hotkey] No alternate hotkey set.")
        return

    # Setup new hotkey using string format (much simpler and more reliable)
    try:
        # Convert our format to pynput's expected string format
        # Our format: "ctrl+shift+s" -> pynput format: "<ctrl>+<shift>+s"
        hotkey_parts = new_hotkey.split("+")
        pynput_parts = []

        for part in hotkey_parts:
            part = part.strip().lower()
            # Map our format to pynput's format
            if part in ["ctrl", "control"]:
                pynput_parts.append("<ctrl>")
            elif part in ["alt"]:
                pynput_parts.append("<alt>")
            elif part in ["shift"]:
                pynput_parts.append("<shift>")
            elif part in ["win", "cmd", "meta"]:
                pynput_parts.append("<cmd>")
            else:
                # Regular keys don't need brackets
                pynput_parts.append(part)

        pynput_hotkey = "+".join(pynput_parts)

        # Create GlobalHotKeys with the string format
        hotkey_listener = keyboard.GlobalHotKeys({pynput_hotkey: launch_snipping_tool})
        hotkey_listener.start()
        logging.info(f"[Hotkey] Set up listener for: {new_hotkey} -> {pynput_hotkey}")

    except Exception as e:
        logging.error(f"[Hotkey] Error setting up hotkey '{new_hotkey}': {e}")
        current_hotkey = ""


def launch_tray():
    tray_path = os.path.join(EXE_DIR, "sniplens.py")
    subprocess.Popen([sys.executable, tray_path])


def kill_tray():
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"]
            if cmdline and any("sniplens.py" in part for part in cmdline):
                proc.kill()
        except Exception:
            continue


def md5_image(pixels):
    return hashlib.md5(pixels).hexdigest()


@clipboard_locked
def grab_clipboard_image_and_hash():
    try:
        pixels, width, height = copykitten.paste_image()
        return md5_image(pixels), (pixels, width, height)
    except Exception:
        pass
    try:
        img = ImageGrab.grabclipboard()
        if img is None:
            return None, None
        img = img.convert("RGBA")
        width, height = img.size
        pixels = img.tobytes()
        return md5_image(pixels), (pixels, width, height)
    except Exception as e:
        logging.warning(f"[Clipboard] ImageGrab failed: {e}")
        return None, None


def get_settings():
    try:
        with open(SETTINGS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def get_tray_status():
    raw = get_settings()
    val = raw.get("tray_status", 0)
    if isinstance(val, dict) and "value" in val:
        return int(val["value"])
    return int(val)


def get_auto_upload_enabled():
    raw = get_settings()
    val = raw.get("auto_upload_enabled", True)
    if isinstance(val, dict) and "value" in val:
        return bool(val["value"])
    return bool(val)


def get_clipboard_sites():
    raw = get_settings()
    val = raw.get("clipboard_sites")
    sites = val["value"] if isinstance(val, dict) and "value" in val else val
    return sites if isinstance(sites, list) and sites else DEFAULT_CLIPBOARD_SITES


def get_default_clipboard_site():
    sites = get_clipboard_sites()
    raw = get_settings()
    val = raw.get("default_clipboard_site_id")
    default_id = val["value"] if isinstance(val, dict) and "value" in val else val
    for site in sites:
        if site.get("id") == default_id and site.get("enabled", True):
            return site
    for site in sites:
        if site.get("enabled", True):
            return site
    return None


@clipboard_locked
def get_clipboard_owner_process_name():
    try:
        hwnd = win32clipboard.GetClipboardOwner()
        if not hwnd:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name().lower()
    except Exception:
        return None


def update_settings(updates: dict, delete_keys: list = None):
    """Safely update settings, with an option to delete keys."""
    try:
        try:
            with open(SETTINGS_PATH, "r") as f:
                raw = json.load(f)
        except Exception:
            raw = {}

        if delete_keys:
            for key in delete_keys:
                if key in raw:
                    del raw[key]

        raw.update(updates)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(raw, f, indent=4)
    except Exception as e:
        logging.error("Failed to update settings: %s", e)


@clipboard_locked
def get_clipboard_text():
    try:
        win32clipboard.OpenClipboard()
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return None
    except Exception:
        return None
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass


# Incremented each time a site watcher starts; older watchers see the change and
# exit, so only the most recent snip opens a site when text is copied.
site_watcher_generation = 0


def watch_clipboard_for_site(baseline_text, generation, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(EXIT_WATCHDOG) or generation != site_watcher_generation:
            return
        text = get_clipboard_text()
        if text and text != baseline_text and text.strip():
            site = get_default_clipboard_site()
            if site:
                url = site["url"].replace("<search_term>", quote(text.strip()))
                logging.info(f"[ClipboardSite] Opening {site.get('name', url)}: {url}")
                webbrowser.open_new_tab(url)
            break
        time.sleep(0.5)
    else:
        logging.info("[ClipboardSite] Clipboard watcher timed out after %ds.", timeout)


def upload_and_open_lens(hash_val, image_data, is_tray_snip):
    global site_watcher_generation
    logging.info("[SnippingTool] New clipboard image found.")
    update_settings({"last_detected_image": hash_val})
    tray_status = get_tray_status()

    do_upload = get_auto_upload_enabled() and (
        tray_status == 2 or (tray_status == 1 and is_tray_snip)
    )

    if do_upload and image_data is not None:
        pixels, width, height = image_data
        img = Image.frombytes(mode="RGBA", size=(width, height), data=pixels)
        with BytesIO() as output:
            img.save(output, format="PNG")
            output.seek(0)
            files = {"files[]": ("snip.png", output, "image/png")}
            logging.info("[Uguu] Uploading image...")
            try:
                response = requests.post(
                    "https://uguu.se/upload",
                    files=files,
                    timeout=10,
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success") and data.get("files"):
                        url = data["files"][0]["url"]
                        logging.info(f"[Uguu] Upload success: {url}")
                        update_settings({"last_upload_url": url})
                        lens_url = f"https://lens.google.com/uploadbyurl?url={url}"
                        logging.info(f"[Google Lens] Opening: {lens_url}")
                        webbrowser.open_new_tab(lens_url)
                        site_watcher_generation += 1
                        baseline = get_clipboard_text()
                        threading.Thread(
                            target=watch_clipboard_for_site,
                            args=(baseline, site_watcher_generation),
                            daemon=True,
                        ).start()
                    else:
                        logging.error(f"[Uguu] Upload failed: {data}")
                else:
                    logging.error(
                        f"[Uguu] Upload failed with status: {response.text}"
                    )
            except Exception as e:
                logging.error(f"[Uguu] Upload error: {e}")
    else:
        logging.info("[SnippingTool] No upload or duplicate or not allowed.")


def clipboard_monitor_loop():
    # SnippingTool.exe runs persistently on Windows 11, so the process-close
    # transition never fires. Use clipboard polling keyed on the snip token instead.
    pending_token = None
    token_set_time = None
    token_baseline_hash = None
    always_on_baseline_hash, _ = grab_clipboard_image_and_hash()

    while True:
        if os.path.exists(EXIT_WATCHDOG):
            break

        settings = get_settings()
        tray_snip_token = settings.get("tray_snip_token")
        val = settings.get("tray_status", 0)
        tray_status = int(val["value"] if isinstance(val, dict) else val)

        if tray_snip_token and tray_snip_token != pending_token:
            pending_token = tray_snip_token
            token_set_time = time.time()
            token_baseline_hash, _ = grab_clipboard_image_and_hash()
            logging.info(f"[SnippingTool] Watching clipboard for token: {pending_token}")

        if pending_token and token_set_time:
            if time.time() - token_set_time > 30.0:
                logging.info(f"[SnippingTool] Timed out waiting for snip: {pending_token}")
                if get_settings().get("tray_snip_token") == pending_token:
                    update_settings({}, delete_keys=["tray_snip_token"])
                pending_token = None
                token_set_time = None
            else:
                hash_val, image_data = grab_clipboard_image_and_hash()
                if hash_val and hash_val != token_baseline_hash:
                    logging.info(f"[SnippingTool] Detected close. Checking clipboard...")
                    if get_settings().get("tray_snip_token") == pending_token:
                        logging.info(f"Consumed snip token: {pending_token}")
                        update_settings({}, delete_keys=["tray_snip_token"])
                    upload_and_open_lens(hash_val, image_data, is_tray_snip=True)
                    always_on_baseline_hash = hash_val
                    pending_token = None
                    token_set_time = None

        if not pending_token and tray_status == 2:
            hash_val, image_data = grab_clipboard_image_and_hash()
            if hash_val and hash_val != always_on_baseline_hash:
                always_on_baseline_hash = hash_val
                owner = get_clipboard_owner_process_name()
                # Snip tools often leave no clipboard owner, so unknown is allowed.
                if owner is None or owner in SNIP_TOOL_PROCESS_NAMES:
                    logging.info("[SnippingTool] Detected close. Checking clipboard...")
                    upload_and_open_lens(hash_val, image_data, is_tray_snip=False)
                else:
                    logging.info(
                        f"[SnippingTool] Ignored clipboard image from non-snip source: {owner}"
                    )

        time.sleep(0.5)


def watchdog_tray_monitor():
    missing_counter = 0
    check_interval = 1
    max_missing = 5

    while True:
        if os.path.exists(EXIT_WATCHDOG):
            break

        if not is_tray_running():
            missing_counter += 1
            if missing_counter >= max_missing:
                logging.info("[Watchdog] Tray app missing. Signaling watchdog exit.")
                with open(EXIT_WATCHDOG, "w") as f:
                    f.write("exit from tray monitor")
                break
        else:
            missing_counter = 0
        time.sleep(check_interval)


def hotkey_monitor_loop():
    """Monitor for hotkey setting changes and update the listener"""
    last_check_time = 0
    check_interval = 2  # Check every 2 seconds

    while True:
        if os.path.exists(EXIT_WATCHDOG):
            break

        current_time = time.time()
        if current_time - last_check_time >= check_interval:
            try:
                setup_hotkey_listener()
            except Exception as e:
                logging.error(f"[Hotkey] Error in hotkey monitor: {e}")
            last_check_time = current_time

        time.sleep(0.5)


class SettingsHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.last_state = tray_setting()
        if self.last_state and not is_tray_running():
            launch_tray()
        elif not self.last_state and is_tray_running():
            kill_tray()

        # Setup initial hotkey listener
        setup_hotkey_listener()

    def on_modified(self, event):
        if os.path.abspath(event.src_path) == os.path.abspath(SETTINGS_PATH):
            current_state = tray_setting()
            if current_state != self.last_state:
                if current_state:
                    if not is_tray_running():
                        launch_tray()
                else:
                    kill_tray()
                self.last_state = current_state

            # Check for hotkey changes
            setup_hotkey_listener()


def cleanup_hotkey_listener():
    """Clean up the hotkey listener on exit"""
    global hotkey_listener
    if hotkey_listener:
        try:
            hotkey_listener.stop()
            logging.info("[Hotkey] Cleaned up hotkey listener on exit.")
        except Exception as e:
            logging.error(f"[Hotkey] Error cleaning up hotkey listener: {e}")


if __name__ == "__main__":
    try:
        os.remove(EXIT_WATCHDOG)
    except OSError:
        pass

    # Register cleanup for hotkey listener
    atexit.register(cleanup_hotkey_listener)

    if not is_tray_running():
        launch_tray()

    logging.info("[Watchdog] Starting background threads.")
    threading.Thread(target=clipboard_monitor_loop, daemon=True).start()
    threading.Thread(target=watchdog_tray_monitor, daemon=True).start()

    # Start hotkey monitor thread if hotkeys are available
    if HOTKEY_AVAILABLE:
        threading.Thread(target=hotkey_monitor_loop, daemon=True).start()
        logging.info("[Watchdog] Hotkey monitoring enabled.")
    else:
        logging.info("[Watchdog] Hotkey monitoring disabled (pynput not available).")

    observer = Observer()
    event_handler = SettingsHandler()
    observer.schedule(event_handler, EXE_DIR, recursive=False)
    observer.start()
    try:
        while not os.path.exists(EXIT_WATCHDOG):
            time.sleep(0.2)

        logging.info("[Watchdog] Exit signal received. Shutting down.")

        try:
            os.remove(EXIT_WATCHDOG)
        except OSError:
            pass

    except KeyboardInterrupt:
        logging.info("[Watchdog] Keyboard interrupt received. Shutting down.")
        with open(EXIT_WATCHDOG, "w") as f:
            f.write("exit from keyboard interrupt")

    finally:
        cleanup_hotkey_listener()
        observer.stop()
        observer.join()
        logging.info("[Watchdog] Observer stopped. Exiting.")
