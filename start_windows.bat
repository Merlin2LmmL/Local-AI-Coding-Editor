@echo off
setlocal EnableDelayedExpansion
title AI Code Assistant — Setup ^& Launch
color 0A

echo ============================================================
echo   AI Code Assistant — Local Setup (Windows)
echo ============================================================
echo.

:: ── 0. Detect GPU ──────────────────────────────────────────────
echo [0/5] Detecting GPU...
set "GPU_NAME=Unknown GPU"
set "GPU_VRAM=? MB"
for /f "tokens=*" %%G in ('powershell -Command "(Get-WmiObject Win32_VideoController | Where-Object { $_.Name -notmatch 'Parsec|Microsoft|Remote' } | Sort-Object AdapterRAM -Descending | Select-Object -First 1).Name" 2^>nul') do (
    set "GPU_NAME=%%G"
)
for /f "tokens=*" %%V in ('powershell -Command "$regPath = 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0000'; $vram = (Get-ItemProperty -Path $regPath -Name 'HardwareInformation.qwMemorySize' -ErrorAction SilentlyContinue).'HardwareInformation.qwMemorySize'; if ($vram) { [math]::Round($vram / 1MB) } else { '' }" 2^>nul') do (
    set "GPU_VRAM=%%V MB"
)
echo        GPU: %GPU_NAME%
echo        VRAM: %GPU_VRAM%
echo.

:: ── 1. Check / Install Ollama ──────────────────────────────────
where ollama >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [1/5] Ollama not found. Downloading installer...
    powershell -Command "Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile '%TEMP%\OllamaSetup.exe'"
    if not exist "%TEMP%\OllamaSetup.exe" (
        echo ERROR: Failed to download Ollama installer.
        echo Please install manually from https://ollama.com/download
        pause
        exit /b 1
    )
    echo [1/5] Installing Ollama silently...
    start /wait "" "%TEMP%\OllamaSetup.exe" /S
    set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
    where ollama >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: Ollama installed but not found on PATH.
        echo Please restart this script or add Ollama to your PATH.
        pause
        exit /b 1
    )
    echo [1/5] Ollama installed successfully!
) else (
    echo [1/5] Ollama already installed. OK
)

:: ── 2. Start Ollama server (if not running) ────────────────────
echo [2/5] Ensuring Ollama server is running...

:: Force Vulkan backend for AMD GPUs to fully utilize them
echo %GPU_NAME% | find /I "AMD" >nul
if %ERRORLEVEL% EQU 0 set "USE_VULKAN=1"
echo %GPU_NAME% | find /I "Radeon" >nul
if %ERRORLEVEL% EQU 0 set "USE_VULKAN=1"

if defined USE_VULKAN (
    echo        AMD GPU detected. Enabling Vulkan backend for Ollama.
    set "OLLAMA_VULKAN=1"
    :: Kill existing ollama process to ensure it restarts with Vulkan
    taskkill /F /IM ollama.exe >nul 2>&1
)

tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if %ERRORLEVEL% NEQ 0 (
    start "" ollama serve
    timeout /t 3 /nobreak >nul
)
echo        Ollama server ready.

:: ── 3. Check models ────────────────────────────────────────────
echo [3/5] Skipping model downloads...
echo        Models can be configured directly in Settings.

:: ── 4. Python virtual environment + dependencies ───────────────
echo [4/5] Setting up Python environment...
cd /d "%~dp0"

if not exist ".venv" (
    echo        Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo        Installing Python dependencies...
pip install -r requirements.txt --quiet --disable-pip-version-check
echo        Dependencies installed.

:: ── 5. Launch the GUI ──────────────────────────────────────────
echo [5/5] Launching AI Code Assistant...
echo.
echo ============================================================
echo   GPU:     %GPU_NAME% (%GPU_VRAM%)
echo   Planner: gemma4:12b
echo   Coder:   qwen2.5-coder:14b
echo   Ready!   The assistant window should open now.
echo ============================================================
echo.
python gui.py

endlocal
