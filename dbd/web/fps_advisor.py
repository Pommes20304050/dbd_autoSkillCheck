import configparser
import os
import re
import shutil
import sys
import threading
from pathlib import Path

try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False


GAME_USER_SETTINGS_RELATIVE = Path("DeadByDaylight/Saved/Config/WindowsClient/GameUserSettings.ini")
# DBD only ships on Windows — its INI lives under %LOCALAPPDATA%. On Linux/macOS
# the file does not exist, so we shortcut the read/write paths and the UI shows
# a "not supported on this OS" hint instead of a misleading "INI not found".
_IS_WINDOWS = sys.platform.startswith("win")
# Serializes /api/set-fps-cap so two parallel POSTs (or this app and the game
# itself rewriting the file on shutdown) can't interleave a read-modify-write.
_INI_WRITE_LOCK = threading.Lock()
# DBD subclasses UE's GameUserSettings — its custom section comes first; standard UE section is the fallback.
DBD_SECTIONS = ("/Script/DeadByDaylight.DBDGameUserSettings", "/Script/Engine.GameUserSettings")

# Standard caps the user can pick from the UI. 120 is the upper bound DBD itself enforces in the menu.
STANDARD_CAPS = [30, 60, 90, 120]

# DBD process names — checked before writing the INI. If DBD is running, our
# edit is doomed: DBD only reads GameUserSettings.ini at startup, AND it
# rewrites the file with its in-memory settings when it exits, silently
# undoing our change. Refusing the write up-front beats a confusing
# "I clicked 30 but the game stayed at 120".
_DBD_PROCESS_NAMES = (
    "deadbydaylight-win64-shipping.exe",
    "deadbydaylight.exe",
)


def _is_dbd_running():
    """True if a DBD-looking process is alive. Returns False on any error
    (psutil missing, permissions, race) — we'd rather attempt the write than
    block the user because of a probe failure."""
    if not _PSUTIL_OK:
        return False
    try:
        for p in psutil.process_iter(["name"]):
            try:
                name = (p.info.get("name") or "").lower()
            except Exception:
                continue
            if name in _DBD_PROCESS_NAMES:
                return True
    except Exception:
        return False
    return False


def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))


def find_ini() -> Path:
    return _localappdata() / GAME_USER_SETTINGS_RELATIVE


def read_game_fps_cap():
    if not _IS_WINDOWS:
        return None, "not_windows", str(find_ini())
    ini_path = find_ini()
    if not ini_path.exists():
        return None, "ini_not_found", str(ini_path)

    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        cfg.read(ini_path, encoding="utf-8-sig")
    except configparser.Error as e:
        return None, f"ini_parse_error: {e}", str(ini_path)

    section = next((s for s in DBD_SECTIONS if cfg.has_section(s)), None)
    if section is None:
        return None, "section_missing", str(ini_path)

    raw = cfg.get(section, "FrameRateLimit", fallback=None)
    if raw is None:
        return None, "key_missing", str(ini_path)

    try:
        cap = float(raw)
    except ValueError:
        return None, f"value_unparsable: {raw!r}", str(ini_path)

    return cap, "ok", str(ini_path)


def set_game_fps_cap(new_cap):
    """Write the new FPS cap into DBD's GameUserSettings.ini.
    Updates BOTH `frameratelimit` and `fpslimitmode` in DBD's custom section.
    Preserves the original line ordering / formatting (does NOT round-trip via configparser).
    Returns (ok: bool, message: str)."""
    if not _IS_WINDOWS:
        return False, "FPS cap writing is only supported on Windows (Dead by Daylight is Windows-only)."
    if not isinstance(new_cap, int) or isinstance(new_cap, bool):
        return False, f"Invalid cap {new_cap!r}. Must be an integer."
    if new_cap not in STANDARD_CAPS:
        return False, f"Invalid cap {new_cap}. Must be one of {STANDARD_CAPS}."

    if _is_dbd_running():
        return False, ("Dead by Daylight is running — close the game first, "
                       "then change the FPS cap. DBD overwrites GameUserSettings.ini "
                       "on exit, so any change made while it's running is lost.")

    with _INI_WRITE_LOCK:
        ini_path = find_ini()
        if not ini_path.exists():
            return False, f"INI not found: {ini_path}"

        try:
            text = ini_path.read_text(encoding="utf-8-sig")
        except OSError as e:
            return False, f"Read failed: {e}"

        # Make a one-time backup the first time we touch the file, so the user
        # can restore the pristine DBD config if anything goes sideways.
        backup = ini_path.with_suffix(ini_path.suffix + ".dbd-asc-backup")
        if not backup.exists():
            try:
                shutil.copy2(ini_path, backup)
            except OSError as e:
                # Backup failure is non-fatal but worth surfacing — if a later
                # write also fails, the user still has the original on disk.
                print(f"Warning: FPS-cap backup failed: {e}")

        new_text, replaced_keys = _replace_fps_keys_in_text(text, float(new_cap))
        if not replaced_keys:
            return False, "No FrameRateLimit / FPSLimitMode keys found to update."

        # Atomic write: write a tmp file then os.replace so a crash mid-write
        # never leaves a half-written GameUserSettings.ini.
        tmp_path = ini_path.with_suffix(ini_path.suffix + ".dbd-asc-tmp")
        try:
            tmp_path.write_text(new_text, encoding="utf-8")
            os.replace(tmp_path, ini_path)
        except OSError as e:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            return False, f"Write failed: {e}"

    return True, f"Set FPS cap to {new_cap}. Restart Dead by Daylight for it to take effect. (Updated: {', '.join(replaced_keys)})"


def _replace_fps_keys_in_text(text, new_cap):
    """Line-wise rewrite: keeps INI ordering/comments/casing intact.
    Replaces values for `frameratelimit` (float) and `fpslimitmode` (int) keys
    only inside DBD-related sections."""
    lines = text.splitlines(keepends=True)
    out = []
    in_dbd_section = False
    replaced = []

    section_re = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
    keys_floats = re.compile(r"^(?P<lead>\s*)(?P<key>frameratelimit)(?P<sep>\s*=\s*).*$", re.IGNORECASE)
    keys_ints = re.compile(r"^(?P<lead>\s*)(?P<key>fpslimitmode)(?P<sep>\s*=\s*).*$", re.IGNORECASE)

    for line in lines:
        m = section_re.match(line)
        if m:
            in_dbd_section = m.group("name") in DBD_SECTIONS
            out.append(line)
            continue

        if in_dbd_section:
            mf = keys_floats.match(line)
            if mf:
                new_line = f"{mf.group('lead')}{mf.group('key')}{mf.group('sep')}{new_cap:.6f}\n"
                out.append(new_line)
                replaced.append(mf.group("key"))
                continue
            mi = keys_ints.match(line)
            if mi:
                new_line = f"{mi.group('lead')}{mi.group('key')}{mi.group('sep')}{int(new_cap)}\n"
                out.append(new_line)
                replaced.append(mi.group("key"))
                continue

        out.append(line)

    return "".join(out), replaced


def recommend_cap(tool_fps_avg, current_cap):
    """Return the smallest standard cap that the tool can plausibly sustain
    (i.e. the smallest cap >= tool_fps_avg). Returns None if no change recommended."""
    if tool_fps_avg is None:
        return None
    candidates = [c for c in STANDARD_CAPS if c >= tool_fps_avg]
    if not candidates:
        # Tool is faster than the highest cap → 120 is fine
        target = STANDARD_CAPS[-1]
    else:
        target = candidates[0]
    if current_cap is not None and abs(current_cap - target) < 1:
        return None  # already at the recommended cap (or within rounding)
    return target


def build_advice(tool_fps_avg):
    """Compare the rolling average tool FPS to the game's configured FPS cap.

    The README of this project explicitly states that BOTH the game and the AI
    tool must run at >= 60 fps for great-hits to land reliably. This advisor
    surfaces that requirement at runtime.
    """
    cap, status, path = read_game_fps_cap()

    base = {
        "tool_fps_avg": tool_fps_avg,
        "ini_status": status,
        "ini_path": path,
        "standard_caps": STANDARD_CAPS,
        "recommended_cap": None,
    }

    if status == "not_windows":
        return {
            **base,
            "game_fps_cap": None,
            "severity": "info",
            "message": "Game FPS cap reading is Windows-only (Dead by Daylight does not run on this OS).",
            "recommendation": None,
        }
    if status != "ok":
        return {
            **base,
            "game_fps_cap": None,
            "severity": "info",
            "message": "Couldn't read game FPS cap from GameUserSettings.ini.",
            "recommendation": None,
        }

    base["recommended_cap"] = recommend_cap(tool_fps_avg, cap)

    if cap == 0.0:
        # 0.0 means uncapped / VSync — fall back to the absolute 60 fps floor.
        if tool_fps_avg is not None and tool_fps_avg < 60:
            return {
                **base,
                "game_fps_cap": 0.0,
                "severity": "danger",
                "message": f"Tool averages {tool_fps_avg:.1f} fps — below the 60 fps minimum the project requires for reliable great-hits.",
                "recommendation": "Switch to GPU mode, raise CPU workload, or close background apps.",
            }
        return {
            **base,
            "game_fps_cap": 0.0,
            "severity": "info",
            "message": "Game FPS cap is unlimited / VSync — only the tool FPS is checked.",
            "recommendation": None,
        }

    if tool_fps_avg is None:
        return {
            **base,
            "game_fps_cap": cap,
            "severity": "info",
            "message": f"Game capped at {cap:.0f} fps. Run the tool for a few seconds to compare.",
            "recommendation": None,
        }

    rec = base["recommended_cap"]

    # Tool is below the absolute 60 fps floor → highest severity, regardless of cap.
    if tool_fps_avg < 60:
        if cap > 60:
            message = (f"Tool averages {tool_fps_avg:.1f} fps — far below the 60 fps minimum. "
                       f"Game is capped at {cap:.0f} fps, the gap is severe.")
            recommendation = (f"Lower in-game FPS cap to {rec or 60} fps, or switch the tool to GPU mode."
                              if rec else "Switch to GPU mode, raise CPU workload, or close background apps.")
        else:
            message = f"Tool averages {tool_fps_avg:.1f} fps — below the 60 fps minimum required for reliable great-hits."
            recommendation = "Switch to GPU mode, raise CPU workload, or close background apps."
        return {**base, "game_fps_cap": cap, "severity": "danger",
                "message": message, "recommendation": recommendation}

    # Tool >= 60 fps but significantly below the game cap → warn the user.
    if tool_fps_avg < cap * 0.7:
        return {
            **base, "game_fps_cap": cap, "severity": "warn",
            "message": f"Tool averages {tool_fps_avg:.1f} fps, but the game is capped at {cap:.0f} fps. Skill checks may be missed.",
            "recommendation": (f"Lower the in-game FPS cap to {rec} fps so the tool keeps pace."
                               if rec else "Lower the in-game FPS cap so the tool keeps pace."),
        }

    # Tool below cap but within 30% — soft warning.
    if tool_fps_avg < cap - 5:
        return {
            **base, "game_fps_cap": cap, "severity": "warn",
            "message": f"Tool averages {tool_fps_avg:.1f} fps, game at {cap:.0f} fps — close but not matched.",
            "recommendation": (f"For safer hits, lower game cap to {rec} fps."
                               if rec else "Acceptable. For safer hits, lower game cap to match tool."),
        }

    # All good.
    return {
        **base, "game_fps_cap": cap, "severity": "ok",
        "message": f"Tool averages {tool_fps_avg:.1f} fps · Game cap {cap:.0f} fps. In sync.",
        "recommendation": None,
    }
