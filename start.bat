@echo off
rem ai-trading-kit: one-time install into a private folder, then the kit's home screen.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Setting up a private Python folder for the kit (once)...
    py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/
        echo and tick "Add python.exe to PATH", then run this again.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -e .
    if errorlevel 1 (
        echo The install did not finish. See the messages above.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m aitk %*
if "%~1"=="" (
    echo.
    echo To use the kit from any terminal: "%~dp0.venv\Scripts\aitk.exe"  (or activate .venv)
    pause
)
endlocal
