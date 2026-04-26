@echo off
REM ============================================================================
REM  DBD Auto Skill Check - Setup
REM  --------------------------------------------------------------------------
REM  Creates a local virtual environment in .venv\, then installs every
REM  Python package the tool needs. Verifies each critical install by
REM  actually importing the module — pip's exit code alone is not trusted,
REM  because broken wheels can install with exit code 0 and still fail to
REM  import at runtime.
REM
REM  Run this ONCE after cloning. After it finishes, use start.bat to launch
REM  the tool. Re-run this script any time requirements.txt changes.
REM ============================================================================

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================================
echo   DBD Auto Skill Check - Setup
echo ============================================================================
echo.

REM ------------------------------------------------------------------ Python --
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not on PATH.
    echo         Install Python 3.10 or newer from https://www.python.org/downloads/
    echo         and re-run this script.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set "PYVER=%%V"
echo [OK] Found Python !PYVER!

REM Reject Python 2.x or anything older than 3.9.
python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.9+ is required - found !PYVER!.
    echo         Install a newer Python and re-run this script.
    pause
    exit /b 1
)

REM ----------------------------------------------------------- venv creation --
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [1/6] Creating virtual environment in .venv\ ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create virtual environment.
        echo         Try:  python -m pip install --user virtualenv
        pause
        exit /b 1
    )
) else (
    echo [1/6] Virtual environment already exists - reusing .venv\
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] Virtual environment looks broken: "%VENV_PY%" missing.
    echo         Delete .venv\ and re-run this script.
    pause
    exit /b 1
)

REM ------------------------------------------------------- upgrade pip first --
echo.
echo [2/6] Upgrading pip / setuptools / wheel ...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [WARN] pip upgrade failed - continuing anyway.
)

REM ------------------------------------------ install requirements.txt deps --
echo.
echo [3/6] Installing required packages from requirements.txt ...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install -r requirements.txt failed.
    echo         Scroll up to see which package errored out.
    pause
    exit /b 1
)

REM --------------------------------------------------- install ONNX Runtime --
echo.
echo [4/6] Installing ONNX Runtime ...

REM Refuse to mix onnxruntime + onnxruntime-gpu - they share DLLs and conflict.
"%VENV_PY%" -m pip uninstall -y onnxruntime onnxruntime-gpu >nul 2>nul

REM Probe for a working NVIDIA driver. `where nvidia-smi` confirms the binary
REM is on PATH; `nvidia-smi -L` confirms it can actually list a GPU.
set "HAS_NVIDIA="
where nvidia-smi >nul 2>nul && nvidia-smi -L >nul 2>nul && set "HAS_NVIDIA=1"

REM If NVIDIA detected, also verify CUDA 13.2+ + cuDNN 9 runtime are present.
REM onnxruntime-gpu 1.25 is built against the CUDA 13 runtime (it dynamically
REM loads cublasLt64_13.dll / cudart64_13.dll). CUDA 12.x SDKs are detected but
REM rejected -- they don't ship the v13 DLLs and onnxruntime silently falls
REM back to CPU at session creation. Minimum we accept: CUDA 13.2.
REM
REM Detection runs in two stages because the user's PATH is often stale:
REM   1) `where` lookup -- catches installs already picked up by a fresh shell.
REM   2) Filesystem scan of NVIDIA's standard install dirs -- catches the
REM      common "just installed, didn't reboot" case AND the cuDNN install
REM      location which is NOT auto-added to PATH at all
REM      (C:\Program Files\NVIDIA\CUDNN\v9.x\bin\).
set "CUDA_OK="
set "CUDNN_OK="
set "CUDA_VER="
set "CUDA_MAJOR="
set "CUDA_MINOR="
if defined HAS_NVIDIA (
    REM ---- CUDA: try PATH first ----
    where nvcc >nul 2>nul
    if not errorlevel 1 (
        for /f "tokens=5" %%v in ('nvcc --version 2^>^&1 ^| findstr /c:"release"') do set "CUDA_VER=%%v"
        if defined CUDA_VER (
            set "CUDA_VER=!CUDA_VER:,=!"
            for /f "tokens=1,2 delims=." %%a in ("!CUDA_VER!") do (
                set "CUDA_MAJOR=%%a"
                set "CUDA_MINOR=%%b"
            )
        )
    )
    REM ---- CUDA fallback: scan default install dirs for nvcc.exe ----
    REM Prefer v13.* (the version we actually need) over v12.*, so messaging
    REM reports the highest installed major even on dual-install systems.
    if not defined CUDA_MAJOR (
        for /d %%D in ("%ProgramFiles%\NVIDIA GPU Computing Toolkit\CUDA\v13.*") do (
            if exist "%%D\bin\nvcc.exe" (
                set "CUDA_VER=%%~nxD"
                set "CUDA_VER=!CUDA_VER:v=!"
                for /f "tokens=1,2 delims=." %%a in ("!CUDA_VER!") do (
                    set "CUDA_MAJOR=%%a"
                    set "CUDA_MINOR=%%b"
                )
            )
        )
    )
    if not defined CUDA_MAJOR (
        for /d %%D in ("%ProgramFiles%\NVIDIA GPU Computing Toolkit\CUDA\v12.*") do (
            if exist "%%D\bin\nvcc.exe" (
                set "CUDA_VER=%%~nxD"
                set "CUDA_VER=!CUDA_VER:v=!"
                for /f "tokens=1,2 delims=." %%a in ("!CUDA_VER!") do (
                    set "CUDA_MAJOR=%%a"
                    set "CUDA_MINOR=%%b"
                )
            )
        )
    )
    REM ---- Accept CUDA 13.2+ (or any CUDA 14+) ----
    REM Default CUDA_MINOR to 0 if unset, so the GEQ check below is well-formed
    REM (empty operands trigger a batch syntax error).
    if not defined CUDA_MINOR set "CUDA_MINOR=0"
    if "!CUDA_MAJOR!"=="13" (
        if !CUDA_MINOR! GEQ 2 set "CUDA_OK=1"
    )
    if defined CUDA_MAJOR (
        for /f "delims=" %%n in ("!CUDA_MAJOR!") do if %%n GEQ 14 set "CUDA_OK=1"
    )

    REM ---- cuDNN: try PATH first ----
    where cudnn64_9.dll >nul 2>nul && set "CUDNN_OK=1"
    REM ---- cuDNN fallback: scan NVIDIA\CUDNN\v9.* install dirs ----
    REM The cuDNN 9 installer ships several layouts:
    REM   A:  ...\NVIDIA\CUDNN\v9.x\bin\cudnn64_9.dll                    (flat)
    REM   B:  ...\NVIDIA\CUDNN\v9.x\bin\<cuda-ver>\cudnn64_9.dll         (cuda-versioned)
    REM   C:  ...\NVIDIA\CUDNN\v9.x\bin\<cuda-ver>\x64\cudnn64_9.dll     (cuda+arch, current installer)
    if not defined CUDNN_OK (
        for /d %%D in ("%ProgramFiles%\NVIDIA\CUDNN\v9.*") do (
            if exist "%%D\bin\cudnn64_9.dll" set "CUDNN_OK=1"
            for /d %%S in ("%%D\bin\*") do (
                if exist "%%S\cudnn64_9.dll" set "CUDNN_OK=1"
                if exist "%%S\x64\cudnn64_9.dll" set "CUDNN_OK=1"
            )
        )
    )
    REM ---- cuDNN fallback: user-copied DLLs inside CUDA's own bin\ folder ----
    if not defined CUDNN_OK (
        for /d %%D in ("%ProgramFiles%\NVIDIA GPU Computing Toolkit\CUDA\v12.*") do (
            if exist "%%D\bin\cudnn64_9.dll" set "CUDNN_OK=1"
        )
        for /d %%D in ("%ProgramFiles%\NVIDIA GPU Computing Toolkit\CUDA\v13.*") do (
            if exist "%%D\bin\cudnn64_9.dll" set "CUDNN_OK=1"
        )
    )
)

set "GPU_RT_OK="
if defined CUDA_OK if defined CUDNN_OK set "GPU_RT_OK=1"

set "ORT_FLAVOR="
if defined HAS_NVIDIA (
    if defined GPU_RT_OK (
        echo       NVIDIA GPU + CUDA !CUDA_VER! + cuDNN 9 detected - installing onnxruntime-gpu.
        "%VENV_PY%" -m pip install --upgrade onnxruntime-gpu
        "%VENV_PY%" -c "import onnxruntime" >nul 2>nul && set "ORT_FLAVOR=GPU"
        if not defined ORT_FLAVOR (
            echo [WARN] onnxruntime-gpu installed but cannot be imported - falling back to CPU build.
            "%VENV_PY%" -m pip uninstall -y onnxruntime onnxruntime-gpu >nul 2>nul
        )
    ) else (
        echo.
        echo ============================================================================
        echo   NVIDIA GPU detected, but the GPU runtime is incomplete:
        if defined CUDA_OK (
            echo     - CUDA 13.2+: OK ^(found !CUDA_VER!^)
        ) else (
            if defined CUDA_VER (
                echo     - CUDA 13.2+: MISSING ^(found !CUDA_VER!, need 13.2 or newer^)
            ) else (
                echo     - CUDA 13.2+: MISSING ^(nvcc not found on PATH or in default install dirs^)
            )
        )
        if defined CUDNN_OK (
            echo     - cuDNN 9:    OK
        ) else (
            echo     - cuDNN 9:    MISSING ^(cudnn64_9.dll not found on PATH or in default install dirs^)
        )
        echo.
        echo   GPU mode requires BOTH. Opening the missing component's download page.
        echo   Install what's missing, reboot, then re-run setup.bat to enable GPU mode.
        echo.
        echo   For now, falling back to CPU-only ONNX Runtime so the tool still works.
        echo ============================================================================
        if not defined CUDA_OK start "" "https://developer.nvidia.com/cuda-13-2-0-download-archive"
        if not defined CUDNN_OK start "" "https://developer.nvidia.com/cudnn-downloads"
        echo.
        echo   Press any key to continue with CPU install ...
        pause >nul
    )
) else (
    echo       No NVIDIA GPU detected - installing onnxruntime [CPU].
)

if not defined ORT_FLAVOR (
    "%VENV_PY%" -m pip install --upgrade onnxruntime
    "%VENV_PY%" -c "import onnxruntime" >nul 2>nul && set "ORT_FLAVOR=CPU"
)

if not defined ORT_FLAVOR (
    echo.
    echo [ERROR] Could not install a working ONNX Runtime.
    echo         Run manually:
    echo             .venv\Scripts\python.exe -m pip install onnxruntime
    echo         and check the error pip prints.
    pause
    exit /b 1
)
echo [OK] ONNX Runtime !ORT_FLAVOR! installed and importable.

REM --------------------------------------- Windows-only optional speed-ups --
echo.
echo [5/6] Installing optional Windows extras (pywin32) ...
"%VENV_PY%" -m pip install --upgrade pywin32
if errorlevel 1 (
    echo [WARN] pywin32 install failed - the tool will still work,
    echo        but key sending may be slower.
)

REM Old versions of this tool installed bettercam; remove it if present so
REM nothing tries to import it from a stale site-packages.
"%VENV_PY%" -m pip uninstall -y bettercam >nul 2>nul

REM ------------------------------------------------ final health check --------
echo.
echo [6/6] Verifying installation ...
"%VENV_PY%" -c "import flask, numpy, cv2, mss, PIL, psutil, onnxruntime"
if errorlevel 1 (
    echo.
    echo [ERROR] One or more required modules failed to import.
    echo         Setup is incomplete - the tool will not start.
    echo         Try re-running setup.bat. If the same module keeps failing,
    echo         install it manually:
    echo             .venv\Scripts\python.exe -m pip install ^<package^>
    pause
    exit /b 1
)
echo [OK] All required modules import cleanly.

REM ------------------------------------------------- model files sanity check --
if not exist "models" (
    mkdir "models"
)

dir /b "models\*.onnx" "models\*.trt" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [INFO] No model files found in .\models\.
    echo        Drop your .onnx ^(or .trt for TensorRT^) model into the models\ folder
    echo        before starting the tool. The README explains where to grab one.
)

echo.
echo ============================================================================
echo   Setup complete.
echo.
echo   Next step:  double-click start.bat
echo ============================================================================
echo.
pause
endlocal
