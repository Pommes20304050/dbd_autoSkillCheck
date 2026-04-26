# Chapter 10 — Setup, Install & OS-Level Errors

Comprehensive guide for 35+ error codes users encounter during installation and runtime of dbd_autoSkillCheck on Windows or Linux. Covers Python detection, venv creation, pip package installation, GPU/CUDA setup, Windows security, and Linux/macOS platform-specific issues.

## E.SETUP.001 — Python Not on PATH
**Trigger:** setup.bat cannot find python on PATH.
**Fix:** Install Python 3.12 from python.org with "Add Python to PATH" enabled.

## E.SETUP.002 — Python 2.x Found Instead of 3.x
**Trigger:** Python 2.7 found instead of 3.x.
**Fix:** Uninstall Python 2.7 or use python3 command.

## E.SETUP.003 — Python 3.x Too Old
**Trigger:** Python 3.8 or earlier.
**Fix:** Install Python 3.12+.

## E.SETUP.004 — Multiple Python Installs
**Trigger:** Wrong python found first in PATH.
**Fix:** Use py -3.12 setup.bat.

## E.SETUP.005 — venv Creation Fails
**Trigger:** python -m venv .venv fails.
**Windows:** Reinstall Python with venv component.
**Linux:** sudo apt-get install python3-venv.

## E.SETUP.006 — venv Broken After Creation
**Trigger:** .venv/Scripts/python.exe missing.
**Fix:** Delete .venv, free disk space, disable antivirus, move from cloud.

## E.SETUP.007 — pip Upgrade Fails (TLS)
**Trigger:** pip install --upgrade pip fails with SSL.
**Fix:** Sync system time, try alternate PyPI, configure proxy.

## E.SETUP.008 — Firewall Blocking PyPI
**Trigger:** Network blocks pypi.org.
**Fix:** Contact IT, whitelist domain, or use offline packages.

## E.SETUP.009 — pip Install Fails (Network)
**Trigger:** pip install -r requirements.txt fails midway.
**Fix:** Clear cache, free disk, retry with --default-timeout=1000.

## E.SETUP.010 — onnxruntime Conflict
**Trigger:** Both CPU and GPU versions installed.
**Fix:** Uninstall both, clear cache, recreate venv.

## E.SETUP.011 — NumPy 2.x ABI Break
**Trigger:** NumPy 2.0+ with ONNX Runtime less than 1.18.
**Fix:** Upgrade ONNX Runtime or downgrade NumPy to less than 2.0.

## E.SETUP.012 — OpenCV Wheel Mismatch
**Trigger:** OpenCV for NumPy 1.x with NumPy 2.x.
**Fix:** Reinstall OpenCV or downgrade NumPy.

## E.SETUP.013 — Pillow Build Fails (Linux)
**Trigger:** pip builds Pillow from source; fails.
**Ubuntu:** sudo apt-get install libjpeg-dev libzlib1-dev.
**RHEL:** sudo dnf install libjpeg-devel zlib-devel.

## E.SETUP.014 — pywin32 Needs Admin
**Trigger:** pywin32 installed without Admin.
**Fix:** Right-click setup.bat, Run as administrator.

## E.SETUP.015 — pythonnet Wheel Mismatch
**Trigger:** pythonnet wheel for wrong Python version.
**Fix:** Reinstall pythonnet.

## E.SETUP.016 — BetterCam on Non-Windows
**Trigger:** Install bettercam on Linux/macOS.
**Fix:** Use MSS instead (cross-platform).

## E.SETUP.017 — CUDA Without cuDNN
**Trigger:** CUDA Toolkit present, cuDNN missing.
**Fix:** Download cuDNN from developer.nvidia.com/cudnn.

## E.SETUP.018 — CUDA Driver Too Old
**Trigger:** Driver 520.x but CUDA Toolkit 12.0.
**Fix:** Update driver from nvidia.com/Download.

## E.SETUP.019 — TensorRT Version Mismatch
**Trigger:** .trt engine from newer TensorRT version.
**Fix:** Regenerate engine or update TensorRT.

## E.SETUP.020 — Visual C++ Runtime Missing
**Trigger:** ONNX Runtime DLL cannot load.
**Fix:** Download Visual C++ Redistributable from support.microsoft.com.

## E.SETUP.021 — Antivirus Quarantining DLL
**Trigger:** AV flags onnxruntime.dll (false positive).
**Fix:** Restore from quarantine, exclude .venv.

## E.SETUP.022 — SmartScreen Blocking start.bat
**Trigger:** SmartScreen warning on first run.
**Fix:** Click Run anyway or unblock in Properties.

## E.SETUP.023 — Defender Slowing Load
**Trigger:** First model load takes 30-60 seconds.
**Fix:** Exclude models folder from Defender.

## E.SETUP.024 — Port 7860 In Use
**Trigger:** Another app on port 7860.
**Fix:** Kill other process or change port.

## E.SETUP.025 — Browser Auto-Open Fails
**Trigger:** Flask launches but browser doesn't open.
**Fix:** Navigate manually to http://127.0.0.1:7860.

## E.SETUP.026 — Browser Opens Early
**Trigger:** Browser opens before Flask ready.
**Fix:** Wait and refresh, increase delay.

## E.SETUP.027 — No Administrator
**Trigger:** start.bat run without Admin.
**Fix:** Right-click start.bat, Run as administrator.

## E.SETUP.028 — Path with Non-ASCII
**Trigger:** Project in unusual folder names.
**Fix:** Move to C:\dev\dbd_autoSkillCheck.

## E.SETUP.029 — OneDrive Locking Files
**Trigger:** Project in OneDrive.
**Fix:** Move out or pause OneDrive.

## E.SETUP.030 — WSL2 GPU Not Configured
**Trigger:** Running in WSL2 without NVIDIA setup.
**Fix:** Install NVIDIA CUDA for WSL2.

## E.SETUP.031 — Linux BetterCam N/A
**Trigger:** BetterCam unavailable on Linux.
**Fix:** Use MSS (default).

## E.SETUP.032 — Linux pynput Needs X11
**Trigger:** Running on Wayland.
**Fix:** Switch to X11 session.

## E.SETUP.033 — Linux evdev Permissions
**Trigger:** /dev/uinput access denied.
**Fix:** sudo usermod -a -G input $USER.

## E.SETUP.034 — macOS TCC Screen Recording
**Trigger:** Screen recording permission prompt.
**Fix:** Click Allow in dialog.

## E.SETUP.035 — macOS pynput Accessibility
**Trigger:** Accessibility permission prompt.
**Fix:** Click Allow in dialog.

---

Summary: Comprehensive error documentation for dbd_autoSkillCheck setup and runtime.

File: error_doc_chapters/10_setup_runtime.md
Version: 1.0
Entries: 35
Tool: dbd_autoSkillCheck v3.0+ with Flask UI fork
