"""Build a separate demonstration database from a week of the NASA FIRMS archive.

The live database holds the latest near-real-time week. A week from another season shows what that week may lack:
crop-residue burning and forest fires next to industry. NASA FIRMS publishes yearly country files (standard
processing, with NASA's own static-source flag in the "type" column). This script cuts them to a date window and to the
focus regions, keeps the cut as CSV next to the new database, and builds that database with land cover, the full
analysis and the GIS layer store. It also writes run_archive_demo.bat, which opens the week on port 8001. The live
database is never touched. Rebuilding the same week starts from empty tables but keeps the land cover already fetched.

Usage (from the project root):
    py backend/scripts/build_archive_dataset.py --csv viirs-snpp_2024_India.csv --csv modis_2024_India.csv --start 2024-04-24
    py backend/scripts/build_archive_dataset.py --csv viirs-snpp_2024_India.csv --start 2024-04-01 --days 30 --count

Yearly files: https://firms.modaps.eosdis.nasa.gov/country/ (for example data/country/viirs-snpp/2024/viirs-snpp_2024_India.csv).
"""
import argparse
import asyncio
import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
ARCHIVE_ROOT = os.path.join(BACKEND_DIR, "app", "data", "archive")
sys.path.insert(0, BACKEND_DIR)

from app.pipeline.regions import FOCUS_REGIONS  # noqa: E402  (plain definitions; the app configuration is read later)


def region_of(regions, lat: float, lon: float):
    for region in regions:
        west, south, east, north = region["bbox"]
        if south <= lat <= north and west <= lon <= east:
            return region["id"]
    return None


def count(paths, regions, start: str, end: str) -> None:
    """Print detections per day and region, to choose a window."""
    per_day = defaultdict(Counter)
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if start <= row["acq_date"] <= end:
                    per_day[row["acq_date"]][region_of(regions, float(row["latitude"]), float(row["longitude"])) or "elsewhere"] += 1
    names = [r["id"] for r in regions] + ["elsewhere"]
    print("date        " + " ".join(f"{name[:14]:>14}" for name in names))
    for day in sorted(per_day):
        print(f"{day}  " + " ".join(f"{per_day[day][name]:>14}" for name in names))


def write_launcher(name: str, label: str) -> str:
    """run_archive_demo.bat: the API and dashboard on port 8001 with this archive database, polling off."""
    path = os.path.join(PROJECT_DIR, "run_archive_demo.bat")
    lines = [
        "@echo off",
        "echo ====================================================================",
        "echo  GeoThermal Sentinel - archive week (http://127.0.0.1:8001)",
        "echo  A fixed dataset in its own database; the live server stays on port 8000.",
        "echo ====================================================================",
        "setlocal",
        f'set "GEOTHERMAL_DB_PATH=%~dp0backend\\app\\data\\archive\\{name}\\geothermal.db"',
        f'set "GEOTHERMAL_GIS_STORE_PATH=%~dp0backend\\app\\data\\archive\\{name}\\gis\\geothermal_sentinel.gpkg"',
        'set "GEOTHERMAL_STATIC_DATASET=1"',
        f'set "GEOTHERMAL_DATASET_LABEL={label}"',
        'cd /d "%~dp0backend"',
        "py -m uvicorn app.main:app --host 127.0.0.1 --port 8001",
        "pause",
    ]
    with open(path, "w", newline="\r\n", encoding="ascii", errors="replace") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", action="append", required=True, help="FIRMS yearly country CSV (repeat for each sensor)")
    parser.add_argument("--start", required=True, help="first day, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--regions", help="comma-separated focus region ids (default: every focus region)")
    parser.add_argument("--all-india", action="store_true", help="keep every detection, not only those in the focus regions")
    parser.add_argument("--name", help="dataset folder name (default: the start date)")
    parser.add_argument("--label", help="dataset name shown in the dashboard")
    parser.add_argument("--max-detections", type=int, default=20000, help="stop when the cut is larger (the dashboard loads at most 20,000)")
    parser.add_argument("--skip-landcover", action="store_true")
    parser.add_argument("--count", action="store_true", help="only print detections per day and region")
    args = parser.parse_args()

    wanted = set(args.regions.split(",")) if args.regions else None
    regions = [r for r in FOCUS_REGIONS if wanted is None or r["id"] in wanted]
    if not regions:
        raise SystemExit(f"No known region in --regions; choose from {', '.join(r['id'] for r in FOCUS_REGIONS)}")
    start = date.fromisoformat(args.start)
    end = start + timedelta(days=args.days - 1)
    if args.count:
        count(args.csv, regions, start.isoformat(), end.isoformat())
        return

    name = args.name or start.isoformat()
    target = os.path.join(ARCHIVE_ROOT, name)
    os.makedirs(target, exist_ok=True)
    cut, per_region = [], Counter()
    for path in args.csv:
        kept = []
        with open(path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not start.isoformat() <= row["acq_date"] <= end.isoformat():
                    continue
                region = region_of(regions, float(row["latitude"]), float(row["longitude"]))
                if region is None and not args.all_india:
                    continue
                kept.append(row)
                per_region[region or "elsewhere"] += 1
            fieldnames = reader.fieldnames
        stem = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(target, f"{stem}_{start:%Y%m%d}-{end:%Y%m%d}.csv")
        with open(out_path, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(kept)
        print(f"[+] {os.path.basename(path)}: kept {len(kept)} detections -> {os.path.relpath(out_path, PROJECT_DIR)}")
        cut.extend(kept)
    print(f"[+] Per region: {dict(per_region)}")
    if len(cut) > args.max_detections:
        raise SystemExit(f"{len(cut)} detections is more than --max-detections {args.max_detections}; choose fewer days or regions")

    db_path = os.path.join(target, "geothermal.db")
    os.environ["GEOTHERMAL_DB_PATH"] = db_path
    os.environ["GEOTHERMAL_GIS_STORE_PATH"] = os.path.join(target, "gis", "geothermal_sentinel.gpkg")
    os.environ["GEOTHERMAL_STATIC_DATASET"] = "1"

    from app.db.database import SessionLocal
    from app.db.models import (AuditLogModel, DetectionModel, DetectionReviewModel, ImageryEvidenceModel, IncidentModel,
                               IngestionRunModel, ThermalSourceModel)
    from app.pipeline.service import service

    window = f"{start:%d %b} to {end:%d %b %Y}" if start.month != end.month else f"{start:%d} to {end:%d %b %Y}"
    scope = "all of India" if args.all_india else f"{len(regions)} focus regions"
    label = args.label or f"Archive week {window} - NASA FIRMS standard processing, {scope}"
    service.startup()
    with SessionLocal() as db:  # start from empty tables, keeping the land cover already fetched for this week
        for model in (DetectionReviewModel, ImageryEvidenceModel, IncidentModel, ThermalSourceModel, DetectionModel, IngestionRunModel, AuditLogModel):
            db.query(model).delete()
        db.commit()
    service.startup()

    async def build():
        if not args.skip_landcover:
            coordinates = [(float(r["latitude"]), float(r["longitude"])) for r in cut]
            keys = service.landcover.missing_cells([c for c in coordinates if service.geo.in_india(*c)])
            print(f"[+] Fetching ESA WorldCover land cover for {len(keys)} footprints (Microsoft Planetary Computer) ...", flush=True)
            print(f"[+] Land cover: {await service.landcover.fetch_cells(keys, concurrency=10, deadline_s=7200.0)}", flush=True)
        return await service.ingest(cut, "firms_archive", label, fetch_landcover=False, extra_details={
            "archive_files": [os.path.basename(p) for p in args.csv], "window": [start.isoformat(), end.isoformat()],
            "regions": [r["id"] for r in regions] if not args.all_india else "all_india"})

    result = asyncio.run(build())
    detections = service.snapshot["detections"]
    sources = service.snapshot["sources"]
    print(f"[+] {result['message']}")
    print(f"[+] Window: {service.snapshot['window']}")
    print(f"[+] Categories: {dict(Counter(d['category'] for d in detections))}")
    print(f"[+] Classes: {dict(Counter(d['class_code'] for d in detections))}")
    print(f"[+] Severity: {dict(Counter(d['severity'] for d in detections))}")
    print(f"[+] Needs verification: {sum(1 for d in detections if d['verification_required'])}")
    print(f"[+] Persistent sources: {len(sources)} {dict(Counter(s['class_code'] for s in sources))}")
    print(f"[+] Analysis: {result['details'].get('analysis')}")
    launcher = write_launcher(name, label)
    print(f"[+] Open the week with {os.path.basename(launcher)} (http://127.0.0.1:8001); the live dashboard stays on port 8000.")
    print(f"[+] Real-data checks: py backend/ml/evaluate_real.py --db {os.path.relpath(db_path, PROJECT_DIR)} --key archive_data_checks")


if __name__ == "__main__":
    main()
