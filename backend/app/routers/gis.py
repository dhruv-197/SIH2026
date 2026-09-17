"""GIS layers: the analysis results as an OGC GeoPackage and as per-layer GeoJSON."""
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ..config import settings
from ..pipeline.gis_store import layer_summary, layer_to_geojson, write_geopackage
from ..pipeline.service import service

router = APIRouter(prefix="/gis", tags=["GIS layers"])


@router.get("/layers")
def layers() -> Dict[str, Any]:
    """The GIS layers and the state of the GeoPackage layer store."""
    store = settings.GIS_STORE_PATH
    exists = os.path.exists(store)
    return {
        "crs": "EPSG:4326 (WGS 84)",
        "layers": layer_summary(service.gis_layers()),
        "store": {
            "format": "OGC GeoPackage 1.4",
            "path": store,
            "exists": exists,
            "size_bytes": os.path.getsize(store) if exists else None,
            "updated_at": datetime.fromtimestamp(os.path.getmtime(store), timezone.utc).isoformat(timespec="seconds") if exists else None,
            "last_write": service.gis_store_status,
        },
        "open_with": "QGIS, ArcGIS Pro, GDAL/OGR (ogrinfo, ogr2ogr) or GeoPandas",
    }


@router.get("/geopackage")
def geopackage(background: BackgroundTasks):
    """Every layer in one GeoPackage file, generated from the current data."""
    handle, path = tempfile.mkstemp(suffix=".gpkg")
    os.close(handle)
    write_geopackage(path, service.gis_layers())
    background.add_task(os.remove, path)
    window = service.snapshot.get("window") or {}
    filename = f"geothermal_sentinel_{window.get('start', 'no-data')}_{window.get('end', 'no-data')}.gpkg"
    return FileResponse(path, media_type="application/geopackage+sqlite3", filename=filename)


@router.get("/layers/{layer_name}.geojson")
def layer_geojson(layer_name: str):
    layer = next((layer for layer in service.gis_layers() if layer.name == layer_name), None)
    if layer is None:
        raise HTTPException(status_code=404, detail="Unknown layer")
    return JSONResponse(layer_to_geojson(layer), media_type="application/geo+json",
                        headers={"Content-Disposition": f'attachment; filename="{layer_name}.geojson"'})
