@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo ERROR: Expected .venv inside E:\MCP-Thesis . Please create it before proceeding.
 pause
 exit /b 1
)
set "PY=.venv\Scripts\python.exe"
echo Project folder: %CD%
echo Checking dependencies ...
"%PY%" -m pip check
if errorlevel 1 (pause & exit /b 1)
echo Running automated code tests ...
"%PY%" -m pytest -q
if errorlevel 1 (pause & exit /b 1)
echo Checking Ollama model ...
"%PY%" check_ollama.py
if errorlevel 1 (pause & exit /b 1)
echo Running three-condition LOCAL AI pilot ...
"%PY%" experiment.py --mode ollama --model qwen2.5:1.5b --tasks 1 --suite baselines --faults type_mismatch --out results_ollama_pilot
if errorlevel 1 (pause & exit /b 1)
echo Pilot finished. Inspect results_ollama_pilot and continue with README steps.
pause
