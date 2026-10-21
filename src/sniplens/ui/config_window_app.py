import asyncio
import logging
import os
import sys
import threading
import uuid

import flet as ft

from sniplens import APP_NAME, paths, theme
from sniplens.hotkey import MODIFIER_NAMES, display_hotkey
from sniplens.logging_setup import setup_logging
from sniplens.settings import DEFAULT_CLIPBOARD_SITES, SEARCH_TERM_PLACEHOLDER, SettingsStore
from sniplens.shortcuts import set_app_menu, set_startup

STATUS_COLORS = {
    0: theme.DANGER,
    1: theme.WARNING,
    2: theme.ACCENT,
}

SWITCH_COLORS = {
    0: theme.DANGER,
    1: theme.ACCENT,
}

MONOSPACE_FONT = "Consolas" if paths.IS_WINDOWS else "Menlo" if paths.IS_MAC else "monospace"

LOG_TAIL_BYTES = 8192
LOG_TAIL_LINES = 10

SITES_VISIBLE_ROWS = 3
SITE_ROW_HEIGHT = 48
SITE_ROW_SPACING = 6

# Modifier keys report a side on Linux ("Control Left") while the generic
# names arrive without one.
MODIFIER_KEYS = {
    "control left": "lctrl",
    "control right": "rctrl",
    "alt left": "lalt",
    "alt right": "ralt",
    "shift left": "lshift",
    "shift right": "rshift",
    "meta left": "lwin",
    "meta right": "rwin",
}

GENERIC_MODIFIERS = {"control": "ctrl", "alt": "alt", "shift": "shift", "meta": "win", "cmd": "win"}

# Flet key names that the hotkey vocabulary in sniplens.hotkey spells
# differently; anything not listed here is already spelled the same.
KEY_ALIASES = {
    "arrow up": "up",
    "arrow down": "down",
    "arrow left": "left",
    "arrow right": "right",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    " ": "space",
    "delete": "del",
    "insert": "ins",
    "page up": "pgup",
    "page down": "pgdn",
    "print screen": "printscreen",
}


def format_hotkey(keys):
    modifiers = sorted({k for k in keys if k in MODIFIER_NAMES})
    regulars = sorted({k for k in keys if k not in MODIFIER_NAMES})
    return "+".join(modifiers + regulars)


def build_config_window(page: ft.Page):
    store = SettingsStore()
    settings = store.load()

    page.title = APP_NAME
    page.window.icon = paths.WINDOW_ICON_PATH
    page.window.width = 760
    page.window.height = 760
    page.window.min_width = 700
    page.window.min_height = 700
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    def save(updates):
        settings.update(updates)
        # only the changed keys go to the store, which merges them; writing the
        # whole snapshot back would republish values the main app owns
        store.save(updates)

    def segmented(selected, options, colors, on_change):
        def handler(e):
            e.control.thumb_color = colors[e.control.selected_index]
            on_change(e.control.selected_index)

        return ft.CupertinoSlidingSegmentedButton(
            selected_index=selected,
            thumb_color=colors[selected],
            on_change=handler,
            padding=ft.Padding(10, 0, 10, 0),
            controls=[ft.Text(label, tooltip=tooltip) for label, tooltip in options],
        )

    status_toggle = segmented(
        settings["tray_status"],
        [
            ("Pause", "Disable all features."),
            (
                "Tray Only",
                "Trigger Google Lens searches only if snip is launched from the "
                + ("menu bar." if paths.IS_MAC else "tray."),
            ),
            ("Always On", "Trigger Google Lens searches regardless of where the snip is launched from."),
        ],
        STATUS_COLORS,
        lambda index: save({"tray_status": index}),
    )

    def on_startup_change(index):
        save({"startup": index})
        set_startup(index == 1)

    startup_toggle = segmented(
        settings["startup"],
        [("Off", None), ("On", None)],
        SWITCH_COLORS,
        on_startup_change,
    )

    app_menu_toggle = None
    if paths.IS_LINUX:

        def on_app_menu_change(index):
            save({"app_menu": index})
            set_app_menu(index == 1)

        app_menu_toggle = segmented(
            settings["app_menu"],
            [("Off", None), ("On", None)],
            SWITCH_COLORS,
            on_app_menu_change,
        )

    hotkey_bypass_toggle = segmented(
        int(settings["alternate_hotkey_bypass"]),
        [
            ("Off", None),
            ("On", "Allow the alternate hotkey to perform an image search in Tray Only mode."),
        ],
        SWITCH_COLORS,
        lambda index: save({"alternate_hotkey_bypass": bool(index)}),
    )

    is_capturing_hotkey = [False]
    captured_keys = []

    def refresh_hotkey_field():
        if is_capturing_hotkey[0]:
            hotkey_field.value = display_hotkey(format_hotkey(captured_keys)) or "Recording keys..."
            hotkey_field.helper = "ENTER saves (with no keys, clears it), ESC cancels."
        else:
            hotkey_field.value = display_hotkey(settings["alternate_hotkey"])
            hotkey_field.helper = "Click to capture new hotkey."
        page.update()

    def on_hotkey_field_click(e):
        if not is_capturing_hotkey[0]:
            is_capturing_hotkey[0] = True
            captured_keys.clear()
            refresh_hotkey_field()

    def on_key_down(e: ft.KeyboardEvent):
        if not is_capturing_hotkey[0]:
            return
        if e.key == "Escape":
            is_capturing_hotkey[0] = False
            captured_keys.clear()
            refresh_hotkey_field()
            return
        if e.key == "Enter":
            is_capturing_hotkey[0] = False
            save({"alternate_hotkey": format_hotkey(captured_keys)})
            captured_keys.clear()
            if settings["alternate_hotkey"]:
                logging.info("Alternate hotkey updated to: '%s'", display_hotkey(settings["alternate_hotkey"]))
            else:
                logging.info("Alternate hotkey cleared.")
            refresh_hotkey_field()
            return

        key_name = (e.key or "").lower()
        if key_name in MODIFIER_KEYS:
            captured_keys[:] = [k for k in captured_keys if k not in ("ctrl", "alt", "shift", "win")]
            if MODIFIER_KEYS[key_name] not in captured_keys:
                captured_keys.append(MODIFIER_KEYS[key_name])
        elif key_name not in GENERIC_MODIFIERS:
            current = [k for k in captured_keys if k in MODIFIER_NAMES]
            if e.ctrl and "ctrl" not in current and not any(k in ("lctrl", "rctrl") for k in current):
                current.append("ctrl")
            if e.alt and "alt" not in current and not any(k in ("lalt", "ralt") for k in current):
                current.append("alt")
            if e.shift and "shift" not in current and not any(k in ("lshift", "rshift") for k in current):
                current.append("shift")
            if e.meta and "win" not in current and not any(k in ("lwin", "rwin") for k in current):
                current.append("win")
            current.append(KEY_ALIASES.get(key_name, key_name))
            captured_keys[:] = current
        refresh_hotkey_field()

    hotkey_field = ft.TextField(
        hint_text="Click to capture hotkey",
        value=display_hotkey(settings["alternate_hotkey"]),
        read_only=True,
        on_click=on_hotkey_field_click,
        width=300,
        border=ft.OutlineInputBorder(),
        helper="Click to capture new hotkey.",
    )

    sites_column = ft.Column(spacing=SITE_ROW_SPACING, scroll=ft.ScrollMode.AUTO)

    def save_sites():
        save(
            {
                "clipboard_sites": settings["clipboard_sites"],
                "default_clipboard_site_id": settings["default_clipboard_site_id"],
            }
        )

    def make_site_row(site):
        def on_name_blur(e):
            site["name"] = e.control.value.strip() or site["url"]
            save_sites()

        def on_url_blur(e):
            if e.control.value.strip():
                site["url"] = e.control.value.strip()
                save_sites()
            else:
                e.control.value = site["url"]
                page.update()

        def on_enabled_change(e):
            site["enabled"] = e.control.value
            save_sites()

        def on_delete(e):
            remaining = [s for s in settings["clipboard_sites"] if s["id"] != site["id"]]
            # the store rejects an empty list, so the last site resets to the default
            settings["clipboard_sites"] = remaining or [dict(DEFAULT_CLIPBOARD_SITES[0])]
            if settings["default_clipboard_site_id"] == site["id"]:
                settings["default_clipboard_site_id"] = settings["clipboard_sites"][0]["id"]
            save_sites()
            render_sites()

        return ft.Row(
            [
                ft.Radio(value=site["id"], tooltip="Default site"),
                ft.TextField(
                    value=site["name"],
                    label="Name",
                    width=140,
                    dense=True,
                    border=ft.OutlineInputBorder(),
                    on_blur=on_name_blur,
                ),
                ft.TextField(
                    value=site["url"],
                    label=f"URL template (use {SEARCH_TERM_PLACEHOLDER})",
                    expand=True,
                    dense=True,
                    border=ft.OutlineInputBorder(),
                    on_blur=on_url_blur,
                ),
                ft.Switch(value=site["enabled"], tooltip="Enabled", on_change=on_enabled_change),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="Delete site", on_click=on_delete),
            ]
        )

    def render_sites():
        sites_column.controls = [make_site_row(site) for site in settings["clipboard_sites"]]
        # sized to its rows so a short list leaves no gap; past
        # SITES_VISIBLE_ROWS it scrolls instead of pushing the log down
        rows = min(len(settings["clipboard_sites"]), SITES_VISIBLE_ROWS)
        sites_column.height = rows * SITE_ROW_HEIGHT + (rows - 1) * SITE_ROW_SPACING
        sites_group.value = settings["default_clipboard_site_id"]
        page.update()

    def on_default_site_change(e):
        settings["default_clipboard_site_id"] = e.control.value
        save_sites()

    sites_group = ft.RadioGroup(
        content=sites_column,
        value=settings["default_clipboard_site_id"],
        on_change=on_default_site_change,
    )

    new_site_name = ft.TextField(hint_text="Name", width=140, dense=True, border=ft.OutlineInputBorder())
    new_site_url = ft.TextField(
        hint_text=f"https://example.com/search?q={SEARCH_TERM_PLACEHOLDER}",
        expand=True,
        dense=True,
        border=ft.OutlineInputBorder(),
    )

    def on_add_site(e):
        url = (new_site_url.value or "").strip()
        if not url:
            return
        settings["clipboard_sites"].append(
            {
                "id": str(uuid.uuid4()),
                "name": (new_site_name.value or "").strip() or url,
                "url": url,
                "enabled": True,
            }
        )
        save_sites()
        new_site_name.value = ""
        new_site_url.value = ""
        render_sites()

    add_site_row = ft.Row(
        [
            new_site_name,
            new_site_url,
            ft.IconButton(icon=ft.Icons.ADD, tooltip="Add site", on_click=on_add_site),
        ]
    )

    # a list rather than a read-only TextField, so it can stay scrolled to the
    # newest entry while filling whatever height the sections above leave
    log_list = ft.ListView(expand=True, auto_scroll=True, spacing=2)
    log_field = ft.Container(
        content=ft.Column(
            [ft.Text("Live Log", size=12, color=ft.Colors.ON_SURFACE_VARIANT), log_list],
            spacing=4,
            expand=True,
        ),
        border=ft.Border.all(1, ft.Colors.OUTLINE),
        border_radius=4,
        padding=ft.Padding(12, 6, 12, 8),
        expand=True,
    )

    def show_log(lines):
        log_list.controls = [
            ft.Text(line, size=13, font_family=MONOSPACE_FONT, selectable=True) for line in lines
        ]
        log_list.update()

    mode_columns = [
        ft.Column(
            [ft.Text("Activation Mode", size=22, weight=ft.FontWeight.BOLD), status_toggle],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        ft.Column(
            [ft.Text("Startup", size=22, weight=ft.FontWeight.BOLD), startup_toggle],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    ]
    if app_menu_toggle is not None:
        mode_columns.append(
            ft.Column(
                [ft.Text("App Menu", size=22, weight=ft.FontWeight.BOLD), app_menu_toggle],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

    page.add(
        ft.Column(
            [
                ft.Row(
                    mode_columns,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=50,
                ),
                ft.Container(height=20),
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    "Snipping Tool Alt Hotkey"
                                    if paths.IS_WINDOWS
                                    else "Snip Hotkey",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                hotkey_field,
                                ft.Text(
                                    "Alt Hotkey Bypass",
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                hotkey_bypass_toggle,
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                ft.Container(height=20),
                ft.Text("Clipboard Search Sites", size=18, weight=ft.FontWeight.BOLD),
                sites_group,
                add_site_row,
                log_field,
            ],
            # fills the window so the log takes whatever height is left rather
            # than growing past the bottom edge
            expand=True,
        )
    )
    render_sites()

    async def poll_log():
        shown = None
        while True:
            try:
                # only the tail is read; the log is never rotated and this runs
                # once a second for as long as the window is open
                with open(paths.LOG_FILE, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    f.seek(max(0, f.tell() - LOG_TAIL_BYTES))
                    lines = f.read().decode("utf-8", "replace").splitlines()
                lines = lines[-LOG_TAIL_LINES:] or ["(Log empty.)"]
            except FileNotFoundError:
                lines = ["(No log file found.)"]
            except OSError as e:
                lines = [f"(Error reading log: {e})"]
            # only on change, so scrolling up to read older lines is not undone
            # by the next poll jumping back to the bottom
            if lines != shown:
                show_log(lines)
                shown = lines
            await asyncio.sleep(1)

    page.on_keyboard_event = on_key_down
    # window.center is a coroutine in flet 1.0, so it cannot be called from
    # this synchronous builder
    page.run_task(page.window.center)
    page.run_task(poll_log)

    def close_with_main_app():
        # the main app holds the other end of stdin, so end of file means it
        # has quit or died. A daemon thread, because the process must still
        # exit when the user closes the window first, and os.read, because a
        # daemon thread holding sys.stdin's lock aborts the interpreter at exit
        os.read(sys.stdin.fileno(), 1)
        page.run_task(page.window.close)

    threading.Thread(target=close_with_main_app, daemon=True).start()


def run():
    setup_logging()
    if paths.IS_LINUX:
        # the Flet client renders a black window on hybrid NVIDIA machines
        # unless GL is software-rendered; users can override by exporting it
        os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    ft.run(build_config_window)
