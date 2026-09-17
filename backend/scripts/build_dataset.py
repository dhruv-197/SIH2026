"""(Re)build the database from real data.

Steps: facility catalog -> NASA FIRMS detections (bundled 7-day snapshot or a fresh download of the
public 7-day feed) -> ESA WorldCover land cover for every detection cell -> full analysis.

Usage (from the project root):
    py backend/scripts/build_dataset.py                   # bundled snapshot
    py backend/scripts/build_dataset.py --source public-7d  # download the latest public 7-day feed first
    py backend/scripts/build_dataset.py --skip-landcover   # offline build
"""
import argparse
import asyncio
import glob
import os
import sys
from collections import Counter

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)


def download_public_feed(snapshot_dir: str) -> None:
    import httpx

    from app.config import settings
    from app.pipeline.firms_client import PUBLIC_FEEDS

    os.makedirs(snapshot_dir, exist_ok=True)
    for feed, path in PUBLIC_FEEDS.items():
        url = f"{settings.FIRMS_PUBLIC_BASE}/{path.format(region=settings.FIRMS_REGION, window='7d')}"
        response = httpx.get(url, timeout=120, headers={"User-Agent": settings.HTTP_USER_AGENT}, follow_redirects=True)
        response.raise_for_status()
        with open(os.path.join(snapshot_dir, os.path.basename(path.format(region=settings.FIRMS_REGION, window="7d"))), "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f"[+] {feed}: {response.text.count(chr(10))} lines")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["snapshot", "public-7d"], default="snapshot")
    parser.add_argument("--skip-landcover", action="store_true")
    parser.add_argument("--keep-db", action="store_true", help="add to the existing database instead of rebuilding")
    args = parser.parse_args()

    from app.config import settings

    if not args.keep_db:
        for path in glob.glob(settings.DB_PATH + "*"):
            os.remove(path)
            print(f"[+] Removed {os.path.basename(path)}")
    if args.source == "public-7d":
        for old in glob.glob(os.path.join(settings.FIRMS_SNAPSHOT_DIR, "*.csv")):
            os.remove(old)
        download_public_feed(settings.FIRMS_SNAPSHOT_DIR)

    from app.pipeline.firms_client import load_snapshot
    from app.pipeline.service import service

    service.startup()
    rows, feeds = load_snapshot()
    print(f"[+] Loaded {len(rows)} FIRMS rows: {feeds}")
    result = asyncio.run(service.ingest(rows, "firms_public_nrt", "Bundled FIRMS snapshot (build_dataset.py)",
                                        fetch_landcover=not args.skip_landcover, landcover_deadline_s=3600.0,
                                        extra_details={"feeds": feeds}))
    print(f"[+] {result['message']}")
    if "landcover" in result["details"]:
        print(f"[+] Land cover: {result['details']['landcover']}")
    detections = service.snapshot["detections"]
    print(f"[+] Window: {service.snapshot['window']}")
    print(f"[+] Categories: {dict(Counter(d['category'] for d in detections))}")
    print(f"[+] Classes: {dict(Counter(d['class_code'] for d in detections))}")
    print(f"[+] Severity: {dict(Counter(d['severity'] for d in detections))}")
    print(f"[+] Needs verification: {sum(1 for d in detections if d['verification_required'])}")
    print(f"[+] Persistent sources: {len(service.snapshot['sources'])} {dict(Counter(s['class_code'] for s in service.snapshot['sources']))}")
    print(f"[+] Facilities with detections: {len({d['facility_id'] for d in detections if d['facility_id']})}/{len(service.facilities)}")


if __name__ == "__main__":
    main()
