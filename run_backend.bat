@echo off
echo ====================================================================
echo  GeoThermal Sentinel - API server (http://127.0.0.1:8000/docs)
echo ====================================================================
cd /d "%~dp0backend"
rem First start on an empty database loads the bundled NASA FIRMS snapshot and
rem fetches ESA WorldCover land cover (internet needed; a few minutes).
py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause
