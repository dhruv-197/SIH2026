@echo off
echo ====================================================================
echo  GeoThermal Sentinel - starting API server and dashboard
echo ====================================================================
start "GeoThermal Sentinel API" cmd /c "%~dp0run_backend.bat"
timeout /t 3 /nobreak >nul
start "GeoThermal Sentinel dashboard" cmd /c "%~dp0run_frontend.bat"
echo.
echo API docs:  http://127.0.0.1:8000/docs
echo Dashboard: http://localhost:5173
echo Demo sign-in: analyst / analyst-demo, commander / commander-demo
echo (set ANALYST_PASSWORD and COMMANDER_PASSWORD to change them)
echo ====================================================================
pause
