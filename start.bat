@echo off
rem ai-trading-kit: one-time install into a private folder, then the kit's home screen.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run

echo Setting up a private Python folder for the kit. This happens once.
py -3.11 -m venv .venv 2>nul
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv 2>nul
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if not exist ".venv\Scripts\python.exe" goto nopython
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -e .
if errorlevel 1 goto failed

:run
".venv\Scripts\python.exe" -m aitk %*
if not "%~1"=="" goto end
echo.
echo To use the kit from any terminal: "%~dp0.venv\Scripts\aitk.exe"  or activate .venv first.
pause
goto end

:nopython
echo.
echo Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH", then run this again.
pause
exit /b 1

:failed
echo The install did not finish. See the messages above.
pause
exit /b 1

:end
endlocal
