import logging

from sniplens import paths

try:
    from pynput import keyboard

    HOTKEY_AVAILABLE = True
except ImportError:
    HOTKEY_AVAILABLE = False
    logging.warning("pynput not available. Alternate hotkey functionality disabled.")

MODIFIER_TO_PYNPUT = {
    "ralt": "<alt_r>",
    "lalt": "<alt_l>",
    "alt": "<alt>",
    "rctrl": "<ctrl_r>",
    "lctrl": "<ctrl_l>",
    "ctrl": "<ctrl>",
    "rshift": "<shift_r>",
    "lshift": "<shift_l>",
    "shift": "<shift>",
    "rwin": "<cmd_r>",
    "lwin": "<cmd_l>",
    "win": "<cmd>",
    "meta": "<cmd>",
    # the macOS names, so a hand-edited settings file can use them too
    "roption": "<alt_r>",
    "loption": "<alt_l>",
    "option": "<alt>",
    "rcmd": "<cmd_r>",
    "lcmd": "<cmd_l>",
    "cmd": "<cmd>",
}

# The settings spell modifiers the Windows way on every OS; macOS users see
# them by the names on their keyboard.
MAC_MODIFIER_LABELS = {
    "win": "cmd",
    "lwin": "lcmd",
    "rwin": "rcmd",
    "meta": "cmd",
    "alt": "option",
    "lalt": "loption",
    "ralt": "roption",
}

# pynput reads anything outside angle brackets as a single character, so every
# key with a name rather than a character needs its own entry here or the
# listener refuses the whole combination.
NAMED_KEY_TO_PYNPUT = {
    "space": "<space>",
    "tab": "<tab>",
    "enter": "<enter>",
    "esc": "<esc>",
    "backspace": "<backspace>",
    "del": "<delete>",
    "ins": "<insert>",
    "home": "<home>",
    "end": "<end>",
    "pgup": "<page_up>",
    "pgdn": "<page_down>",
    "up": "<up>",
    "down": "<down>",
    "left": "<left>",
    "right": "<right>",
    "printscreen": "<print_screen>",
    "pause": "<pause>",
    "menu": "<menu>",
}
NAMED_KEY_TO_PYNPUT.update({f"f{number}": f"<f{number}>" for number in range(1, 21)})

MODIFIER_NAMES = frozenset(MODIFIER_TO_PYNPUT)
KEY_NAMES = frozenset(NAMED_KEY_TO_PYNPUT)


def display_hotkey(hotkey):
    if not paths.IS_MAC:
        return hotkey
    return "+".join(MAC_MODIFIER_LABELS.get(part, part) for part in hotkey.split("+"))


def to_pynput_hotkey(hotkey):
    parts = []
    for part in hotkey.split("+"):
        part = part.strip().lower()
        parts.append(
            MODIFIER_TO_PYNPUT.get(part) or NAMED_KEY_TO_PYNPUT.get(part, part)
        )
    return "+".join(parts)


# UCKeyTranslate's modifier state for Shift
_MAC_SHIFT_STATE = 2


def _mac_keycodes():
    """Maps each character of the current keyboard layout to its key code. The
    settings window records a key as the character it typed, so Cmd+Shift+`
    arrives as "~"; the shifted characters are included, and the unshifted
    ones win where both exist."""
    from pynput._util.darwin import keycode_context, keycode_to_string

    keycodes = {}
    with keycode_context() as context:
        for state in (_MAC_SHIFT_STATE, 0):
            for keycode in range(128):
                char = keycode_to_string(context, keycode, state)
                if char:
                    keycodes[char.lower()] = keycode
    return keycodes


class HotkeyController:
    """Keeps exactly one pynput keyboard listener armed for the hotkeys the
    application currently wants. The listener does not suppress, so the keys
    it watches still reach the desktop.

    Injected key events count like physical ones. Keyboard software such as
    AutoHotkey, PowerToys or a vendor keyboard suite can re-inject every key
    the user presses, and pynput's GlobalHotKeys, which drops injected events,
    would never fire for anyone running it."""

    def __init__(self):
        self._listener = None
        self._bindings = []
        self._current = ()
        self._keycodes = {}

    def reconfigure(self, hotkeys):
        """`hotkeys` maps a hotkey in the settings format to its callback. The
        callback for a given combination never varies, so comparing the
        combinations is enough to tell whether the listener must be rebuilt."""
        if not HOTKEY_AVAILABLE or tuple(hotkeys) == self._current:
            return
        self._stop_listener()
        self._current = tuple(hotkeys)
        if not hotkeys:
            logging.info("[Hotkey] No hotkeys to listen for.")
            return
        try:
            if paths.IS_MAC:
                self._keycodes = _mac_keycodes()
            self._bindings = [
                keyboard.HotKey(
                    [self._physical(key) for key in keyboard.HotKey.parse(to_pynput_hotkey(hotkey))],
                    callback,
                )
                for hotkey, callback in hotkeys.items()
            ]
            self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._listener.start()
            logging.info("[Hotkey] Listening for: %s", ", ".join(hotkeys))
        except Exception as e:
            # a combination pynput refuses stays refused, so _current keeps the
            # attempt and the failure is not re-logged on every settings write
            logging.error("[Hotkey] Error setting up hotkeys %s: %s", ", ".join(hotkeys), e)
            self._listener = None

    def stop(self):
        self._stop_listener()
        self._current = ()

    def _on_press(self, key):
        key = self._physical(key)
        for binding in self._bindings:
            binding.press(key)

    def _on_release(self, key):
        key = self._physical(key)
        for binding in self._bindings:
            binding.release(key)

    def _physical(self, key):
        """On macOS pynput names a key by the character it types, and Option or
        Shift change that character (Option+\\ types «), so a hotkey holding
        them would never match. There keys are compared by key code instead."""
        if paths.IS_MAC and isinstance(key, keyboard.KeyCode):
            vk = key.vk
            if vk is None and key.char is not None:
                vk = self._keycodes.get(key.char.lower())
            if vk is not None:
                return keyboard.KeyCode.from_vk(vk)
        if self._listener is None:
            return key
        return self._listener.canonical(key)

    def _stop_listener(self):
        if self._listener is not None:
            try:
                self._listener.stop()
                logging.info("[Hotkey] Stopped listener for: %s", ", ".join(self._current))
            except Exception as e:
                logging.error("[Hotkey] Error stopping listener: %s", e)
            self._listener = None
