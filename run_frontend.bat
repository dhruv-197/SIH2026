@echo off
echo ====================================================================
echo  GeoThermal Sentinel - dashboard (http://localhost:5173)
echo ====================================================================
cd /d "%~dp0frontend"
npm run dev -- --port 5173
pause
