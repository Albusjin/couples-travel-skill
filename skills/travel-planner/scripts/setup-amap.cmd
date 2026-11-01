@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo Amap MCP: real checks first; update Codex config only when ALL checks pass.
echo Enter your Key only in the hidden local Python prompt. Do not send it to chat.
echo Existing Codex config will be backed up before merging travel_amap.
echo.

where py.exe >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto try_python
set "TRAVEL_AMAP_PYTHON=py -3"
goto python_ready

:try_python
where python.exe >nul 2>nul
if errorlevel 1 goto missing_python
python.exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto missing_python
set "TRAVEL_AMAP_PYTHON=python.exe"

:python_ready
where node.exe >nul 2>nul
if errorlevel 1 goto missing_node
where npx.cmd >nul 2>nul
if errorlevel 1 goto missing_node
node.exe -e "const [major, minor] = process.versions.node.split('.').map(Number); process.exit(major > 22 || (major === 22 && minor >= 14) ? 0 : 1)"
if errorlevel 1 goto missing_node
if not defined LOCALAPPDATA goto missing_profile
set "TRAVEL_AMAP_VENV_DIR=%LOCALAPPDATA%\TravelPlanner\amap-setup-venv"
if exist "%TRAVEL_AMAP_VENV_DIR%\Scripts\python.exe" goto venv_ready
%TRAVEL_AMAP_PYTHON% -m venv "%TRAVEL_AMAP_VENV_DIR%"
if errorlevel 1 goto failed

:venv_ready
"%TRAVEL_AMAP_VENV_DIR%\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0..\requirements-amap-setup.txt"
if errorlevel 1 goto failed
"%TRAVEL_AMAP_VENV_DIR%\Scripts\python.exe" "%~dp0setup_amap.py" --apply --prompt-key
if errorlevel 1 goto failed
echo.
echo Check that passed and configuration_written above are both true.
echo Then completely exit and reopen Codex, and check travel_amap in a new chat.
pause
exit /b 0

:missing_python
echo Python 3.11+ is required. Install it with the Python launcher, then rerun.
echo https://www.python.org/downloads/windows/
goto failed

:missing_node
echo Node.js 22.14+ and npm/npx are required. Node.js 24 LTS is recommended.
echo Install Node.js, completely reopen your terminal, and rerun.
echo https://nodejs.org/
goto failed

:missing_profile
echo LOCALAPPDATA is missing. Run under your own normal Windows user account.

:failed
echo.
echo Setup did not complete. Check the error above. Never share your Key or full config.
pause
exit /b 2
