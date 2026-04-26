# Chapter 7 — FPS Advisor & GameUserSettings.ini Errors

## Overview

The FPS Advisor module reads and writes DBD's GameUserSettings.ini file to monitor and adjust the game's frame rate cap. The module handles cross-platform differences, file encoding quirks, concurrent writes, and various failure modes.

---

## E.FPS.001 — Game Not Installed

**Trigger:** read_game_fps_cap() called on Windows; INI missing.

**Where:** fps_advisor.py:37-38

**What it means:** DBD not installed. Expected path in LOCALAPPDATA does not exist.

**Symptoms:** "Couldn't read game FPS cap" message; no cap value; no adjustment capability.

**Root cause(s):** DBD not installed, LOCALAPPDATA not set, or stat() blocked by permissions.

**How to fix:**
1. Install DBD from Steam, Epic, or Microsoft Store
2. Launch the game at least once to generate config
3. Verify LOCALAPPDATA\DeadByDaylight\Saved\Config\WindowsClient\ exists
4. Reload web interface

**Prevention:** Defer INI ops to first-use; distinguish "not installed" from "not configured" in UI.

**Related:** E.FPS.002, E.FPS.003, E.FPS.024

---

## E.FPS.002 — DBD Installed But Never Launched

**Trigger:** DBD installed but never run; INI not auto-created.

**Where:** fps_advisor.py:37-38

**What it means:** Game exists in library but hasn't generated config yet.

**Symptoms:** Same as E.FPS.001.

**Root cause(s):** User installed but never clicked Play; partial install; game won't start.

**How to fix:**
1. Verify DBD installed (Start menu, Steam, Epic)
2. Launch game, wait for main menu
3. Close game, reload web interface

**Prevention:** Check if DBD base directory exists; surface "Install and launch once."

**Related:** E.FPS.001, E.FPS.003

---

## E.FPS.003 — INI in Non-Default Steam Library

**Trigger:** DBD on secondary SSD; config is still in LOCALAPPDATA.

**Where:** fps_advisor.py:29-30

**What it means:** INI always in LOCALAPPDATA regardless of game binary location.

**Symptoms:** None; code works correctly.

**Root cause(s):** Misunderstanding of Windows layout; naive reimplementation.

**How to fix:** No fix needed; current code is correct.

**Prevention:** Document that INI is always in LOCALAPPDATA; add regression test.

**Related:** E.FPS.001, E.FPS.004

---

## E.FPS.004 — Microsoft Store or Epic Sandboxing

**Trigger:** DBD from Microsoft Store or Epic; sandboxed LOCALAPPDATA.

**Where:** fps_advisor.py:25-26

**What it means:** App containers may redirect AppData or restrict access.

**Symptoms:** "Couldn't read game FPS cap" even though game runs.

**Root cause(s):** Containerization, sandboxing, or LOCALAPPDATA override.

**How to fix:**
1. Check Settings → Privacy & Security → App permissions → File system
2. Uninstall from Microsoft Store; install from Steam (no sandbox)
3. Verify Epic launcher runs with user privileges
4. Check LOCALAPPDATA\DeadByDaylight readability

**Prevention:** Detect LOCALAPPDATA access at startup; check multiple app-store paths as fallbacks.

**Related:** E.FPS.001, E.FPS.005, E.FPS.006

---

## E.FPS.005 — INI Marked Read-Only

**Trigger:** set_game_fps_cap() tries to write; file has read-only attribute.

**Where:** fps_advisor.py:80-82, 103-104

**What it means:** Permissions prevent writes (file attribute, NTFS ACL, anti-cheat, parent dir).

**Symptoms:** POST returns 400/500; "Permission denied" or "Access denied"; FPS cap unchanged.

**Root cause(s):** Read-only attribute, NTFS permissions, anti-cheat lock, parent dir read-only.

**How to fix:**
1. Close game completely (check Task Manager)
2. Right-click INI → Properties → uncheck "Read-only"
3. Click Apply, OK
4. Retry FPS cap adjustment
5. If still failing, check NTFS: Properties → Security → ensure "Modify" permission

**Prevention:** Stat file before write; check read-only flag; surface specific error; log errno.

**Related:** E.FPS.006, E.FPS.009

---

## E.FPS.006 — INI Write Race: Game Running

**Trigger:** os.replace() during game runtime; DBD has INI locked.

**Where:** fps_advisor.py:99-111

**What it means:** Windows file lock prevents replacement when game is running.

**Symptoms:** POST returns 500; "The process cannot access the file because it is being used."

**Root cause(s):** User adjusted cap without closing game; game running in background.

**How to fix:**
1. Close DBD completely (kill DeadByDaylight.exe in Task Manager if needed)
2. Retry FPS cap adjustment
3. Relaunch game

**Prevention:** Detect if DeadByDaylight.exe running; disable "Set FPS Cap" button; warn user.

**Related:** E.FPS.005, E.FPS.009, E.FPS.011

---

## E.FPS.007 — Temp File Collision

**Trigger:** Temp file GameUserSettings.ini.dbd-asc-tmp exists; cannot overwrite.

**Where:** fps_advisor.py:101-104

**What it means:** Atomic write uses temp file; stale file from crash blocks new write.

**Symptoms:** POST returns 500; "Cannot create a file when that file already exists" or "Access denied."

**Root cause(s):** Stale temp from previous crash, race condition (despite lock), foreign process.

**How to fix:**
1. Delete LOCALAPPDATA\DeadByDaylight\Saved\Config\WindowsClient\GameUserSettings.ini.dbd-asc-tmp
2. Retry FPS cap adjustment

**Prevention:** Cleanup in exception handler; add pre-write cleanup; log cleanup failures.

**Related:** E.FPS.008, E.FPS.009

---

## E.FPS.008 — Cross-Volume Atomic Write (EXDEV)

**Trigger:** os.replace() fails; LOCALAPPDATA on different filesystem than temp.

**Where:** fps_advisor.py:104

**What it means:** rename() syscall fails across filesystems (rare on Windows, possible with junctions).

**Symptoms:** POST returns 500; "[Errno 18] Invalid cross-device link."

**Root cause(s):** LOCALAPPDATA is symlink/junction to network drive; OneDrive sync changed path.

**How to fix:**
1. Verify LOCALAPPDATA and TEMP on same drive (echo in cmd)
2. Check junctions: fsutil reparsepoint query "C:\Users\<username>\AppData\Local"
3. Move LOCALAPPDATA back to local drive

**Prevention:** Catch errno.EXDEV; fallback to shutil.move(); diagnostic check at startup.

**Related:** E.FPS.007, E.FPS.009

---

## E.FPS.009 — Insufficient Disk Space

**Trigger:** tmp_path.write_text() fails; filesystem full.

**Where:** fps_advisor.py:103

**What it means:** Temp file write runs out of disk space (rare unless drive critically low).

**Symptoms:** POST returns 500; "[WinError 112] Not enough space on disk."

**Root cause(s):** Disk full or nearly full (< 100 MB); quota exceeded on network drive.

**How to fix:**
1. Free up disk space on LOCALAPPDATA drive (usually C:)
2. Retry FPS cap adjustment

**Prevention:** Check disk before write (shutil.disk_usage()); if < 1 MB, return clear error.

**Related:** E.FPS.007, E.FPS.008

---

## E.FPS.010 — Backup File Write Fails (Non-Fatal)

**Trigger:** INI write succeeds but backup copy (shutil.copy2()) fails.

**Where:** fps_advisor.py:88-93

**What it means:** Backup creation fails; code logs warning and continues (backup is nice-to-have).

**Symptoms:** FPS cap adjusted; no error on UI. Warning in logs: "FPS-cap backup failed."

**Root cause(s):** Parent dir read-only, disk space exhausted, file locks, NTFS permissions.

**How to fix:**
1. Ensure WindowsClient dir is writable
2. Check disk space (>= 1 MB free)
3. Close processes holding INI lock
4. Delete stale .dbd-asc-backup; retry

**Prevention:** Surface backup failure as non-blocking warning to user; log specific reason.

**Related:** E.FPS.005, E.FPS.009

---

## E.FPS.011 — INI Parse Error: Invalid ConfigParser Syntax

**Trigger:** cfg.read() raises configparser.Error; INI syntax malformed.

**Where:** fps_advisor.py:40-44

**What it means:** INI exists and is readable but ConfigParser cannot parse it.

**Symptoms:** "Couldn't read game FPS cap" with parse error message.

**Root cause(s):** Corrupted file, manual edit with syntax errors, non-INI file, incomplete sections.

**How to fix:**
1. Close game
2. Open INI in Notepad; look for malformed lines (missing =, garbled text)
3. If mostly gibberish, delete and relaunch game to regenerate
4. If manually edited, revert changes

**Prevention:** Log full ConfigParser exception with line number; suggest "Delete and relaunch game."

**Related:** E.FPS.012, E.FPS.013

---

## E.FPS.012 — INI Encoding: BOM or Non-UTF-8 Legacy

**Trigger:** INI has BOM or uses Latin-1/UTF-16 instead of UTF-8.

**Where:** fps_advisor.py:42

**What it means:** ConfigParser with "utf-8-sig" can read UTF-8+BOM but fails on UTF-16.

**Symptoms:** "Couldn't read game FPS cap" error; UnicodeDecodeError in logs.

**Root cause(s):** INI from old DBD version, corruption, user edit changed encoding.

**How to fix:**
1. Open INI in Notepad
2. File → Save As; select UTF-8; save
3. Close, reopen in Notepad to verify
4. Reload web interface

**Prevention:** Try utf-8-sig first, fallback to utf-16; log detected encoding; always write utf-8.

**Related:** E.FPS.011, E.FPS.013

---

## E.FPS.013 — FrameRateLimit Value Unparsable

**Trigger:** FrameRateLimit=<value> found but value not convertible to float.

**Where:** fps_advisor.py:54-57

**What it means:** INI key exists but contains non-numeric garbage.

**Symptoms:** "Couldn't read game FPS cap"; error includes value.

**Root cause(s):** Manual edit typo, partial corruption, invalid DBD write.

**How to fix:**
1. Open INI in Notepad
2. Search for FrameRateLimit=; ensure value is number (e.g., 60.000000)
3. If unsure, delete INI and relaunch game to regenerate

**Prevention:** Format output as fixed: {new_cap:.6f} for float, {int(new_cap)} for int.

**Related:** E.FPS.011, E.FPS.014

---

## E.FPS.014 — FrameRateLimit Out of Expected Range

**Trigger:** read_game_fps_cap() gets valid float but unreasonable value (negative, > 500).

**Where:** fps_advisor.py:59; also build_advice() lines 207-224

**What it means:** Value is technically parsable but nonsensical (e.g., -1, 9999).

**Symptoms:** Advisor shows garbled text.

**Root cause(s):** Manual edit typo, corruption, old DBD version range.

**How to fix:**
1. Open INI, locate FrameRateLimit=
2. Verify 0 (uncapped) or 30-240 range
3. Fix or delete INI to regenerate

**Prevention:** Validate in read_game_fps_cap(): if cap < 0 or > 500, return error.

**Related:** E.FPS.013, E.FPS.020

---

## E.FPS.015 — Section Missing in INI

**Trigger:** INI readable but lacks DBD section headers.

**Where:** fps_advisor.py:46-48

**What it means:** ConfigParser reads file but no recognized DBD section found.

**Symptoms:** "Couldn't read game FPS cap"; status = section_missing.

**Root cause(s):** Section headers manually deleted, file replaced, DBD version mismatch.

**How to fix:**
1. Delete GameUserSettings.ini
2. Relaunch DBD; it regenerates INI with correct sections

**Prevention:** Log actual sections found for diagnostics; surface specific error.

**Related:** E.FPS.011, E.FPS.016

---

## E.FPS.016 — FrameRateLimit Key Missing from Section

**Trigger:** INI has valid DBD section but no FrameRateLimit= line (fresh install).

**Where:** fps_advisor.py:50-52

**What it means:** Normal state for new install; absence is not an error.

**Symptoms:** "Couldn't read game FPS cap"; status = key_missing.

**Root cause(s):** Fresh DBD install, graphics settings never opened, INI regenerated.

**How to fix:**
1. No fix needed (not an error)
2. Launch DBD, open graphics settings, set FPS cap, save
3. Reload web interface; key now appears

**Prevention:** Treat key_missing as non-error; use default cap internally.

**Related:** E.FPS.015, E.FPS.024

---

## E.FPS.017 — not_windows Status (Linux/macOS/Proton)

**Trigger:** read_game_fps_cap() called on non-Windows OS.

**Where:** fps_advisor.py:14, 34-35

**What it means:** DBD is Windows-only; INI doesn't exist on Linux/macOS.

**Symptoms:** "Game FPS cap reading is Windows-only"; no cap adjustment buttons.

**Root cause(s):** Tool running on Linux, macOS, or WSL; Proton not detected.

**How to fix:**
- Windows: use a Windows machine
- Linux: DBD via Proton requires future Proton path detection
- macOS: DBD unavailable; use Windows VM or dual boot

**Prevention:** Document Windows-only; detect Proton; resolve game prefix path for future support.

**Related:** E.FPS.018

---

## E.FPS.018 — Proton Prefix INI Path Not Resolved

**Trigger:** DBD runs via Proton on Linux/Steam Deck; tool does not detect prefix.

**Where:** fps_advisor.py:25-30 (not yet implemented)

**What it means:** Proton's virtual Windows prefix is not resolved.

**Symptoms:** On Steam Deck: "Windows-only" even though DBD runs.

**Root cause(s):** Code does not detect Proton or resolve STEAM_COMPAT_TOOL_PATHS.

**How to fix:** Future implementation needed (not yet done).

**Prevention:** Detect Proton at startup; resolve STEAM_COMPAT_TOOL_PATHS; construct prefix path.

**Related:** E.FPS.017

---

## E.FPS.019 — Set Cap to 0 (Uncap/VSync) Not Allowed

**Trigger:** User attempts to set cap=0; validation rejects it (only 30, 60, 90, 120).

**Where:** fps_advisor.py:71-72; server.py validation

**What it means:** API strictly validates against STANDARD_CAPS; 0 valid in DBD but not in whitelist.

**Symptoms:** POST with cap=0 returns 400; "Invalid cap 0. Must be one of [30, 60, 90, 120]."

**Root cause(s):** Validation too strict; advisor handles cap=0 correctly but setter doesn't allow it.

**How to fix:**
1. If you want uncapped, manually disable cap in DBD graphics
2. Close game, reload web interface; advisor treats cap as unlimited

**Prevention:** Update validation to allow 0; OR add 0 to STANDARD_CAPS.

**Related:** E.FPS.020, E.FPS.024

---

## E.FPS.020 — Bool vs. Int Type Confusion

**Trigger:** Client sends cap: true or cap: false instead of integer.

**Where:** fps_advisor.py:69-70

**What it means:** Python bool is subclass of int; explicit check rejects booleans.

**Symptoms:** POST with cap: true returns 400.

**Root cause(s):** Client JavaScript sends true/false; incorrect JSON.

**How to fix:**
1. Client: always send integer {cap: 60}, not {cap: true}
2. Check web UI type safety

**Prevention:** Current code (line 69-70) is correct; add explanatory comment.

**Related:** E.FPS.020

---

## E.FPS.021 — Comments Preserved via Line-Wise Rewrite

**Trigger:** INI has comments (;, #); user writes via _replace_fps_keys_in_text().

**Where:** fps_advisor.py:116-152

**What it means:** Line-wise regex preserves comments; ConfigParser.write() does not.

**Symptoms:** None; comments are preserved correctly.

**Root cause(s):** If switched to ConfigParser.write(), comments lost.

**How to fix:** Keep line-wise method; do NOT switch to cfg.write().

**Prevention:** Document why text replacement is used; add test verifying comments survive.

**Related:** None

---

## E.FPS.022 — _INI_WRITE_LOCK Contention

**Trigger:** Two clients or game itself attempt concurrent writes.

**Where:** fps_advisor.py:17, 74-113

**What it means:** Lock serializes writes; second POST blocks until first completes.

**Symptoms:** Second request delayed; both eventually succeed.

**Root cause(s):** User spam-clicked button, two browser tabs, parallel tests.

**How to fix:** Wait for first request; server handles correctly.

**Prevention:** Disable button during request (show spinner); set 30s timeout; log contention.

**Related:** E.FPS.006

---

## E.FPS.023 — No FrameRateLimit/FPSLimitMode Keys Found

**Trigger:** _replace_fps_keys_in_text() reads INI but neither key found in DBD section.

**Where:** fps_advisor.py:95-97

**What it means:** Section exists but has no keys to replace.

**Symptoms:** POST returns 400; "No FrameRateLimit / FPSLimitMode keys found to update."

**Root cause(s):** Section empty, keys different format/case, old/new DBD version, manual delete.

**How to fix:**
1. Launch DBD, open graphics settings
2. Delete INI, relaunch to regenerate
3. Reload web interface

**Prevention:** Create keys if not found instead of failing; log diagnostic; check case variants.

**Related:** E.FPS.015, E.FPS.016

---

## E.FPS.024 — Advisor Severity Thresholds & Hysteresis

**Trigger:** FPS advisor calculates severity (ok, warn, danger) and recommends cap.

**Where:** fps_advisor.py:155-272, especially 207-272

**What it means:** Thresholds hardcoded; if tool FPS noisy, recommendations oscillate.

**Severity levels:**
- **ok**: Tool FPS >= game cap - 5
- **warn**: Tool FPS < cap * 0.7 or Tool FPS < cap - 5 (but >= 60)
- **danger**: Tool FPS < 60
- **info**: Cap not readable or cap = 0

**Symptoms:** Advisor severity doesn't match user experience; recommended cap jumps.

**Root cause(s):** Tool FPS measurement noisy; thresholds arbitrary; no hysteresis.

**How to fix:** Accept recommendations as guidance; if FPS unstable, use GPU mode; manually set conservative cap.

**Prevention:** Add hysteresis (>10 fps drift); log rolling average; expose confidence score; document thresholds.

**Related:** E.FPS.001

---

## E.FPS.025 — Invalid Cap Range (0 < cap > 1000)

**Trigger:** Client sends cap < 0 or > 1000.

**Where:** server.py:264-265

**What it means:** API validates cap; 1000 upper bound is arbitrary (DBD max approximately 120).

**Symptoms:** POST with cap=2000 returns 400; "cap out of range: 2000."

**Root cause(s):** User trying unrealistic value, malicious request, test data.

**How to fix:** Use 0 or 30-1000; prefer STANDARD_CAPS: 30, 60, 90, 120.

**Prevention:** Update upper bound (240?); document valid range; current validation appropriate.

**Related:** E.FPS.019, E.FPS.020

---

## Summary

25 error codes covering: path/existence, permissions/locks, parse/encoding, value validation, concurrency, advisory logic.

Key themes:
1. Path & Existence: E.FPS.001-004, 017-018
2. Permissions & Locks: E.FPS.005-009
3. Parse & Encoding: E.FPS.011-016
4. Value Validation: E.FPS.013-014, 019-020, 025
5. Concurrency: E.FPS.022
6. Advisory: E.FPS.024

Hardening priorities:
- Game-running preflight check before cap writes
- Distinguish "not found" vs "permission denied" vs "locked"
- Proton support for Linux/Steam Deck
- Hysteresis in advisor recommendations
- Track backup success rate
