@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if defined TRAVEL_PLANNER_PYTHON goto configured_python
where py.exe >nul 2>nul
if errorlevel 1 goto fallback_python
py -3 "%~dp0runtime.py" setup-amap --bootstrap --apply --prompt-key %*
goto finished
:fallback_python
python.exe "%~dp0runtime.py" setup-amap --bootstrap --apply --prompt-key %*
goto finished
:configured_python
"%TRAVEL_PLANNER_PYTHON%" "%~dp0runtime.py" setup-amap --bootstrap --apply --prompt-key %*
:finished
set "TRAVEL_AMAP_STATUS=%ERRORLEVEL%"
pause
exit /b %TRAVEL_AMAP_STATUS%
