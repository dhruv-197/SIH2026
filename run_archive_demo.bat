@echo off
echo ====================================================================
echo  GeoThermal Sentinel - archive week (http://127.0.0.1:8001)
echo  A fixed dataset in its own database; the live server stays on port 8000.
echo ====================================================================
setlocal
set "GEOTHERMAL_DB_PATH=%~dp0backend\app\data\archive\2024-04-24\geothermal.db"
set "GEOTHERMAL_GIS_STORE_PATH=%~dp0backend\app\data\archive\2024-04-24\gis\geothermal_sentinel.gpkg"
set "GEOTHERMAL_STATIC_DATASET=1"
set "GEOTHERMAL_DATASET_LABEL=Archive week 24 to 30 Apr 2024 - NASA FIRMS standard processing, 6 focus regions"
cd /d "%~dp0backend"
py -m uvicorn app.main:app --host 127.0.0.1 --port 8001
pause
