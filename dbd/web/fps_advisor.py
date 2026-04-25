import configparser
import os
from pathlib import Path


GAME_USER_SETTINGS_RELATIVE = Path("DeadByDaylight/Saved/Config/WindowsClient/GameUserSettings.ini")
UE_SECTION = "/Script/Engine.GameUserSettings"


def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))


def find_ini() -> Path:
    return _localappdata() / GAME_USER_SETTINGS_RELATIVE


def read_game_fps_cap():
    ini_path = find_ini()
    if not ini_path.exists():
        return None, "ini_not_found", str(ini_path)

    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        cfg.read(ini_path, encoding="utf-8-sig")
    except configparser.Error as e:
        return None, f"ini_parse_error: {e}", str(ini_path)

    if not cfg.has_section(UE_SECTION):
        return None, "section_missing", str(ini_path)

    raw = cfg.get(UE_SECTION, "FrameRateLimit", fallback=None)
    if raw is None:
        return None, "key_missing", str(ini_path)

    try:
        cap = float(raw)
    except ValueError:
        return None, f"value_unparsable: {raw!r}", str(ini_path)

    return cap, "ok", str(ini_path)


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
    }

    if status != "ok":
        return {
            **base,
            "game_fps_cap": None,
            "severity": "info",
            "message": "Couldn't read game FPS cap from GameUserSettings.ini.",
            "recommendation": None,
        }

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

    # Tool is below the absolute 60 fps floor → highest severity, regardless of cap.
    if tool_fps_avg < 60:
        if cap > 60:
            message = (f"Tool averages {tool_fps_avg:.1f} fps — far below the 60 fps minimum. "
                       f"Game is capped at {cap:.0f} fps, the gap is severe.")
            recommendation = f"Lower in-game FPS cap to 60, or switch the tool to GPU mode."
        else:
            message = f"Tool averages {tool_fps_avg:.1f} fps — below the 60 fps minimum required for reliable great-hits."
            recommendation = "Switch to GPU mode, raise CPU workload, or close background apps."
        return {**base, "game_fps_cap": cap, "severity": "danger",
                "message": message, "recommendation": recommendation}

    # Tool >= 60 fps but significantly below the game cap → warn the user.
    if tool_fps_avg < cap * 0.7:
        target = max(60, int(round(tool_fps_avg / 10) * 10))
        return {
            **base, "game_fps_cap": cap, "severity": "warn",
            "message": f"Tool averages {tool_fps_avg:.1f} fps, but the game is capped at {cap:.0f} fps. Skill checks may be missed.",
            "recommendation": f"Lower the in-game FPS cap to ~{target} fps so the tool keeps pace.",
        }

    # Tool below cap but within 30% — soft warning.
    if tool_fps_avg < cap - 5:
        return {
            **base, "game_fps_cap": cap, "severity": "warn",
            "message": f"Tool averages {tool_fps_avg:.1f} fps, game at {cap:.0f} fps — close but not matched.",
            "recommendation": "Acceptable. For safer hits, lower game cap to match tool, or upgrade tool to GPU mode.",
        }

    # All good.
    return {
        **base, "game_fps_cap": cap, "severity": "ok",
        "message": f"Tool averages {tool_fps_avg:.1f} fps · Game cap {cap:.0f} fps. In sync.",
        "recommendation": None,
    }
