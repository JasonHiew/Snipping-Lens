import re

import pytest
from pynput import keyboard

from sniplens.hotkey import NAMED_KEY_TO_PYNPUT, HotkeyController, to_pynput_hotkey


def test_plain_modifiers():
    assert to_pynput_hotkey("ctrl+shift+s") == "<ctrl>+<shift>+s"


def test_sided_modifiers():
    assert to_pynput_hotkey("ralt+rctrl+\\") == "<alt_r>+<ctrl_r>+\\"
    assert to_pynput_hotkey("lwin+lshift+p") == "<cmd_l>+<shift_l>+p"


def test_meta_alias():
    assert to_pynput_hotkey("meta+a") == "<cmd>+a"


def test_whitespace_tolerated():
    assert to_pynput_hotkey("ctrl + s") == "<ctrl>+s"


def test_named_keys_are_bracketed():
    assert to_pynput_hotkey("f9") == "<f9>"
    assert to_pynput_hotkey("ctrl+space") == "<ctrl>+<space>"
    assert to_pynput_hotkey("ctrl+del") == "<ctrl>+<delete>"
    assert to_pynput_hotkey("alt+up") == "<alt>+<up>"
    assert to_pynput_hotkey("printscreen") == "<print_screen>"


def test_unknown_single_character_passes_through():
    assert to_pynput_hotkey("ctrl+\\") == "<ctrl>+\\"


def skip_keys_this_platform_lacks(pynput_hotkey):
    """pynput only defines the keys its platform has: macOS has no Insert,
    Menu, Pause or Print Screen."""
    missing = [
        name
        for name in re.findall(r"<(\w+)>", pynput_hotkey)
        if not hasattr(keyboard.Key, name)
    ]
    if missing:
        pytest.skip(f"pynput on this platform has no {', '.join(missing)} key")


@pytest.mark.parametrize("name", sorted(NAMED_KEY_TO_PYNPUT))
def test_every_named_key_is_accepted_by_pynput(name):
    hotkey = to_pynput_hotkey(f"ctrl+{name}")
    skip_keys_this_platform_lacks(hotkey)
    keyboard.HotKey.parse(hotkey)


@pytest.mark.parametrize("hotkey", ["win+shift+s", "printscreen", "alt+ctrl+\\"])
def test_system_and_default_hotkeys_are_accepted_by_pynput(hotkey):
    hotkey = to_pynput_hotkey(hotkey)
    skip_keys_this_platform_lacks(hotkey)
    keyboard.HotKey.parse(hotkey)


def test_injected_key_events_fire_hotkeys(monkeypatch):
    """Keyboard software such as AutoHotkey or PowerToys can re-inject every
    physical key press, so a hotkey must fire for injected events too. Events
    are fed through pynput's own listener callbacks, without an OS hook."""
    monkeypatch.setattr(keyboard.Listener, "start", lambda self: None)
    fired = []
    controller = HotkeyController()
    controller.reconfigure({"win+shift+s": lambda: fired.append("snip")})
    listener = controller._listener
    combination = (keyboard.Key.shift, keyboard.Key.cmd, keyboard.KeyCode.from_char("S"))

    for key in combination:
        listener.on_press(key, True)
    assert fired == ["snip"]

    for key in reversed(combination):
        listener.on_release(key, True)
    for key in combination:
        listener.on_press(key, True)
    assert fired == ["snip", "snip"]


def test_mac_modifiers_are_shown_by_their_mac_names(monkeypatch):
    from sniplens import paths
    from sniplens.hotkey import display_hotkey

    monkeypatch.setattr(paths, "IS_MAC", True)
    assert display_hotkey("alt+ctrl+win+\\") == "option+ctrl+cmd+\\"
    assert display_hotkey("lwin+ralt+a") == "lcmd+roption+a"
    assert display_hotkey("") == ""
    monkeypatch.setattr(paths, "IS_MAC", False)
    assert display_hotkey("alt+win+a") == "alt+win+a"


def test_mac_modifier_names_are_accepted_in_settings():
    assert to_pynput_hotkey("cmd+option+a") == "<cmd>+<alt>+a"
    assert to_pynput_hotkey("rcmd+loption+a") == "<cmd_r>+<alt_l>+a"


@pytest.fixture
def mac_controller(monkeypatch):
    from sniplens import hotkey, paths

    monkeypatch.setattr(paths, "IS_MAC", True)
    monkeypatch.setattr(hotkey, "_mac_keycodes", lambda: {"\\": 42, "2": 84, "s": 1, "`": 50, "~": 50})
    monkeypatch.setattr(keyboard.Listener, "start", lambda self: None)
    return HotkeyController()


def test_mac_hotkeys_match_by_key_code(mac_controller):
    """Option changes the character a key types on macOS, so Option+Cmd+\\
    arrives as «; the key code still says which key it was."""
    fired = []
    mac_controller.reconfigure({"alt+win+\\": lambda: fired.append("snip")})
    listener = mac_controller._listener
    for key in (keyboard.Key.alt, keyboard.Key.cmd, keyboard.KeyCode.from_char("«", vk=42)):
        listener.on_press(key, False)
    assert fired == ["snip"]


def test_mac_shifted_and_injected_keys_match(mac_controller):
    fired = []
    mac_controller.reconfigure({"shift+ctrl+2": lambda: fired.append("snip")})
    listener = mac_controller._listener
    for key in (keyboard.Key.shift, keyboard.Key.ctrl, keyboard.KeyCode.from_char("@", vk=84)):
        listener.on_press(key, False)
    assert fired == ["snip"]
    for key in (keyboard.Key.shift, keyboard.Key.ctrl, keyboard.KeyCode.from_char("@", vk=84)):
        listener.on_release(key, False)
    # injected events can carry a character and no key code
    for key in (keyboard.Key.shift, keyboard.Key.ctrl, keyboard.KeyCode.from_char("2")):
        listener.on_press(key, True)
    assert fired == ["snip", "snip"]


def test_mac_hotkey_ignores_other_keys(mac_controller):
    fired = []
    mac_controller.reconfigure({"alt+win+\\": lambda: fired.append("snip")})
    listener = mac_controller._listener
    for key in (keyboard.Key.alt, keyboard.Key.cmd, keyboard.KeyCode.from_char("ß", vk=1)):
        listener.on_press(key, False)
    assert fired == []


def test_mac_hotkey_recorded_as_a_shifted_character(mac_controller):
    """The settings window records Cmd+Shift+` as "~", which has no key of
    its own; it must still match the ` key pressed with Shift."""
    fired = []
    mac_controller.reconfigure({"shift+win+~": lambda: fired.append("snip")})
    listener = mac_controller._listener
    for key in (keyboard.Key.shift, keyboard.Key.cmd, keyboard.KeyCode.from_char("~", vk=50)):
        listener.on_press(key, False)
    assert fired == ["snip"]


def test_mac_keycodes_cover_shifted_characters():
    from sniplens import hotkey, paths

    if not paths.IS_MAC:
        pytest.skip("reads the macOS keyboard layout")
    keycodes = hotkey._mac_keycodes()
    assert keycodes["~"] == keycodes["`"]
