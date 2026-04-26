"""Cross-platform key sender for the auto-hit action.

Windows path uses SendInput (the original implementation — kept verbatim
because games are picky about which input API they accept).
Linux/macOS path uses pynput when available; otherwise falls back to a
no-op so the rest of the app can still import and run (preflight surfaces
the missing capability to the user).
"""
import sys
import time


# Public constants — opaque tokens. The worker passes these to PressKey/ReleaseKey
# without knowing the platform-specific encoding.
SPACE = 0x20
UP = 0x26
DOWN = 0x28
A = 0x41


# Whether key-sending actually works on this platform/install.
KEY_SENDER_AVAILABLE = False
KEY_SENDER_BACKEND = "noop"


if sys.platform.startswith("win"):
    # ── Windows: original SendInput implementation ─────────────────
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    MAPVK_VK_TO_VSC = 0

    wintypes.ULONG_PTR = wintypes.WPARAM

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", wintypes.ULONG_PTR))

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", wintypes.ULONG_PTR))

        def __init__(self, *args, **kwds):
            super().__init__(*args, **kwds)
            if not self.dwFlags & KEYEVENTF_UNICODE:
                self.wScan = user32.MapVirtualKeyExW(self.wVk, MAPVK_VK_TO_VSC, 0)

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD))

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = (("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT))
        _anonymous_ = ("_u",)
        _fields_ = (("type", wintypes.DWORD), ("_u", _U))

    _LPINPUT = ctypes.POINTER(_INPUT)

    def _check_count(result, func, args):
        if result == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return args

    user32.SendInput.errcheck = _check_count
    user32.SendInput.argtypes = (wintypes.UINT, _LPINPUT, ctypes.c_int)

    def PressKey(hexKeyCode):
        x = _INPUT(type=INPUT_KEYBOARD, _u=_INPUT._U(ki=_KEYBDINPUT(wVk=hexKeyCode)))
        user32.SendInput(1, ctypes.byref(x), ctypes.sizeof(x))

    def ReleaseKey(hexKeyCode):
        x = _INPUT(type=INPUT_KEYBOARD,
                   _u=_INPUT._U(ki=_KEYBDINPUT(wVk=hexKeyCode, dwFlags=KEYEVENTF_KEYUP)))
        user32.SendInput(1, ctypes.byref(x), ctypes.sizeof(x))

    KEY_SENDER_AVAILABLE = True
    KEY_SENDER_BACKEND = "win32-sendinput"

else:
    # ── Linux / macOS: try pynput, otherwise no-op ─────────────────
    _pynput_kbd = None
    _vk_to_pynput = None
    try:
        from pynput.keyboard import Controller as _PynputController, Key as _PynputKey
        _pynput_kbd = _PynputController()
        _vk_to_pynput = {
            SPACE: _PynputKey.space,
            UP:    _PynputKey.up,
            DOWN:  _PynputKey.down,
            A:     "a",
        }
        KEY_SENDER_AVAILABLE = True
        KEY_SENDER_BACKEND = "pynput"
    except Exception:
        # pynput missing or display unavailable — keep no-op fallback.
        pass

    if KEY_SENDER_AVAILABLE:
        def PressKey(hexKeyCode):
            k = _vk_to_pynput.get(hexKeyCode)
            if k is not None:
                _pynput_kbd.press(k)

        def ReleaseKey(hexKeyCode):
            k = _vk_to_pynput.get(hexKeyCode)
            if k is not None:
                _pynput_kbd.release(k)
    else:
        def PressKey(hexKeyCode):  # pragma: no cover
            pass

        def ReleaseKey(hexKeyCode):  # pragma: no cover
            pass


if __name__ == "__main__":
    print(f"Backend: {KEY_SENDER_BACKEND} (available={KEY_SENDER_AVAILABLE})")
    if KEY_SENDER_AVAILABLE:
        PressKey(A)
        time.sleep(0.5)
        ReleaseKey(A)
        print("Pressed A")
