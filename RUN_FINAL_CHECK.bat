@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv Python is missing. Place these two files directly in E:\MCP-Thesis.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "MCP_FINAL_CHECK.py"
if errorlevel 1 (
  echo.
  echo CHECK DID NOT PASS. Do not run the old experiments. Copy the exact message above.
) else (
  echo.
  echo SUCCESS. Open the new final_verification folder to see the evidence.
)
echo.
pause
