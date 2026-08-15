@echo off
REM Start the Qlens viewer.
REM
REM   launch.bat                     open on sample runs
REM   launch.bat data\traces.jsonl   open on a trace source
REM
REM Creates or reuses a virtual environment, installs qlens into it, and
REM serves the viewer. Pass --state-dir, --port, or any other qlens view
REM option straight through.

setlocal
cd /d "%~dp0"

REM In-tree .venv, matching the shell launchers. A venv is machine-specific
REM and must never sync; keep it beside the project rather than in the profile.
if defined QLENS_VENV (set "VENV=%QLENS_VENV%") else (set "VENV=.venv")
set "PYTHON=%VENV%\Scripts\python.exe"

python --version >nul 2>&1
if errorlevel 1 (
  echo launch: python is not on PATH. Install Python 3.11 or newer.
  exit /b 1
)

REM An existing directory proves nothing: a venv synced from another
REM machine or left by an interrupted install has a stale interpreter.
"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
  echo launch: creating environment in %VENV%
  if exist "%VENV%" rmdir /s /q "%VENV%"
  python -m venv "%VENV%"
  "%PYTHON%" -m ensurepip --upgrade >nul
)

"%PYTHON%" -c "import qlens" >nul 2>&1
if errorlevel 1 (
  echo launch: installing qlens
  "%PYTHON%" -m pip install --quiet --upgrade pip
  "%PYTHON%" -m pip install --quiet -e ".[qiskit]"
)

if "%~1"=="" (
  echo launch: no trace source given, opening sample runs
  "%PYTHON%" -m qlens.viewer.cli view --demo
  exit /b %errorlevel%
)

"%PYTHON%" -m qlens.viewer.cli view %*
exit /b %errorlevel%
