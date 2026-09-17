"""End-to-end API tests against a temporary database filled with the bundled real FIRMS snapshot."""
import asyncio
import csv
import io
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import settings

pytestmark = pytest.mark.skipif(not os.path.exists(settings.MODEL_BUNDLE_PATH), reason="model bundle not trained")


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from app.pipeline.firms_client import load_snapshot
    from app.pipeline.service import service

    with TestClient(app) as test_client:
        rows, feeds = load_snapshot()
        asyncio.run(service.ingest(rows, "firms_public_nrt", "pytest snapshot", fetch_landcover=False, extra_details={"feeds": feeds}))
        yield test_client


def token(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def csv_rows(text):
    return list(csv.reader(io.StringIO(text)))


def test_health_reports_loaded_real_data(client):
    body = client.get("/api/health").json()
    assert body["detections"] > 1000
    assert body["reference_data"]["osm_features"] > 1000
    assert body["model"]["available"]
    assert body["dataset"] == {"label": None, "static": False} and body["alert_policy_version"].startswith("2.2+")


def test_detections_are_inside_india_and_fully_classified(client):
    body = client.get("/api/detections", params={"limit": 20000}).json()
    assert body["total"] > 1000
    for item in body["items"][:200]:
        assert item["category"] in ("industrial", "vegetation")
        assert item["class_label"]
        assert 6 <= item["latitude"] <= 38 and 68 <= item["longitude"] <= 98
    industrial = client.get("/api/detections", params={"category": "industrial", "limit": 1}).json()["total"]
    vegetation = client.get("/api/detections", params={"category": "vegetation", "limit": 1}).json()["total"]
    assert industrial + vegetation == body["total"]


def test_detection_detail_explains_itself(client):
    item = client.get("/api/detections", params={"limit": 1}).json()["items"][0]
    detail = client.get(f"/api/detections/{item['detection_id']}").json()
    analysis = detail["analysis"]
    assert analysis["evidence"]["statements"]
    assert detail["place"] == item["place"]  # the drawer names the place exactly as the list and map do
    assert len(analysis["contributions"]) == 5
    assert analysis["landcover"]["available"] is False  # offline test run: never guessed
    assert set(analysis["classification"]["probabilities"]) == {"gas_flare", "heavy_industry", "mining_coal_fire", "wildfire", "agricultural"}
    assert analysis["severity"]["policy_version"].startswith("2.2+") and detail["location"]["detections"] >= 1


def test_geojson_export(client):
    response = client.get("/api/detections/export.geojson", params={"category": "industrial"})
    assert response.headers["content-type"].startswith("application/geo+json")
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert all(f["properties"]["category"] == "industrial" for f in body["features"])


def test_detections_export_as_csv(client):
    response = client.get("/api/detections/export.csv", params={"category": "vegetation"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    rows = csv_rows(response.text)
    header = rows[0]
    assert header[:3] == ["latitude", "longitude", "detection_id"] and "review_label" in header
    total = client.get("/api/detections", params={"category": "vegetation", "limit": 1}).json()["total"]
    assert len(rows) - 1 == total and all(row[header.index("category")] == "vegetation" for row in rows[1:])


def test_settings_require_the_right_role(client):
    assert client.patch("/api/settings", json={"zscore_threshold": 5}).status_code == 401
    analyst = token(client, "analyst", "analyst-test")
    assert client.patch("/api/settings", json={"zscore_threshold": 5}, headers=analyst).status_code == 403
    commander = token(client, "commander", "commander-test")
    assert client.patch("/api/settings", json={"zscore_threshold": 99}, headers=commander).status_code == 422
    ok = client.patch("/api/settings", json={"cross_alert_km": 2.5}, headers=commander)
    assert ok.status_code == 200 and ok.json()["settings"]["cross_alert_km"] == 2.5
    assert "firms_api_key" not in client.get("/api/settings").json()["settings"]


def test_wrong_password_is_rejected(client):
    assert client.post("/api/auth/login", json={"username": "commander", "password": "nope"}).status_code == 401


def test_csv_upload_validates_rows(client):
    analyst = token(client, "analyst", "analyst-test")
    csv_text = ("latitude,longitude,bright_ti4,bright_ti5,frp,acq_date,acq_time,daynight,satellite,confidence\n"
                "21.19,81.40,331.2,294.1,3.4,2026-09-13,2010,N,N20,n\n"
                "21.19,81.40,331.2,294.1,,2026-09-13,2010,N,N20,n\n")
    response = client.post("/api/detections/upload", files={"file": ("upload.csv", csv_text, "text/csv")}, headers=analyst)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["records_rejected"] == 1 and body["rejected_sample"][0]["row"] == 3
    only_bad = "latitude,longitude\n1,2\n"
    assert client.post("/api/detections/upload", files={"file": ("bad.csv", only_bad, "text/csv")}, headers=analyst).status_code == 422


def test_drill_creates_a_critical_incident_that_can_be_triaged(client):
    commander = token(client, "commander", "commander-test")
    response = client.post("/api/drills", json={"kind": "industrial_excursion", "facility_id": "IND-STL-002"}, headers=commander)
    assert response.status_code == 200, response.text
    incidents = client.get("/api/incidents", params={"status": "OPEN"}).json()["items"]
    drill = [i for i in incidents if i["is_drill"] and i["incident_type"] == "INDUSTRIAL_EXCURSION"]
    assert drill, incidents[:3]
    incident = drill[0]
    assert incident["severity"] == "CRITICAL"
    assert incident["reason_codes"] == ["ABN_BASELINE_EXCEEDED", "ABN_ABOVE_P90"] and incident["policy_version"].startswith("2.2+")
    bad = client.patch(f"/api/incidents/{incident['id']}", json={"status": "OPEN"}, headers=commander)
    assert bad.status_code in (200, 409)
    ack = client.patch(f"/api/incidents/{incident['id']}", json={"status": "ACKNOWLEDGED", "note": "Called facility"}, headers=commander)
    assert ack.status_code == 200 and ack.json()["history"][-1]["note"] == "Called facility"
    assert client.patch(f"/api/incidents/{incident['id']}", json={"status": "OPEN"}, headers=commander).status_code == 409
    purge = client.delete("/api/drills", headers=commander).json()
    assert purge["detections_removed"] > 0
    assert not any(d["data_source"] == "drill" for d in client.get("/api/detections", params={"limit": 20000}).json()["items"])


def test_untouched_alert_is_withdrawn_and_reopened_when_thresholds_change(client):
    commander = token(client, "commander", "commander-test")
    # An isolated catalog facility (no other mapped feature within 7 km): the fire's distance is to the facility alone.
    response = client.post("/api/drills", json={"kind": "wildfire_near_facility", "facility_id": "IND-CEM-002"}, headers=commander)
    assert response.status_code == 200, response.text

    def drill_alerts():
        return {i["id"]: i for i in client.get("/api/incidents").json()["items"] if i["is_drill"] and i["incident_type"] == "CROSS_ALERT"}

    # The approaching fire can alert both as a fire event and as a location active on several days.
    assert client.patch("/api/settings", json={"cross_alert_km": 2.0}, headers=commander).status_code == 200
    created = [incident_id for incident_id, incident in drill_alerts().items() if incident["status"] == "OPEN"]
    assert created
    assert client.patch("/api/settings", json={"cross_alert_km": 0.5}, headers=commander).status_code == 200
    withdrawn = drill_alerts()
    for incident_id in created:
        assert withdrawn[incident_id]["status"] == "RESOLVED"
        assert withdrawn[incident_id]["history"][-1]["by"] == "system" and "no longer holds" in withdrawn[incident_id]["history"][-1]["note"]
    assert client.patch("/api/settings", json={"cross_alert_km": 2.0}, headers=commander).status_code == 200
    reopened = drill_alerts()
    assert all(reopened[incident_id]["status"] == "OPEN" for incident_id in created)
    assert client.delete("/api/drills", headers=commander).status_code == 200


def test_fire_front_advancing_on_a_facility_raises_a_critical_cross_alert(client):
    commander = token(client, "commander", "commander-test")
    assert client.post("/api/drills", json={"kind": "wildfire_near_facility", "facility_id": "IND-CEM-002"}, headers=commander).status_code == 200
    alerts = [i for i in client.get("/api/incidents", params={"status": "OPEN"}).json()["items"] if i["is_drill"] and i["incident_type"] == "CROSS_ALERT"]
    approaching = [i for i in alerts if (i["details"].get("fire_approach") or {}).get("status") == "approaching"]
    assert approaching, [(i["title"], i["details"]) for i in alerts]
    incident = approaching[0]
    assert incident["severity"] == "CRITICAL" and "FIRE_APPROACHING" in incident["reason_codes"]
    assert incident["title"].startswith("Vegetation fire approaching industrial infrastructure")
    assert incident["details"]["fire_approach"]["closing_rate_km_per_day"] > 0.5
    assert client.delete("/api/drills", headers=commander).status_code == 200


def test_what_if_and_assistant_are_grounded(client):
    body = client.post("/api/detections/what-if", json={"latitude": 30.2, "longitude": 79.2, "frp": 25, "bright_ti4": 350, "bright_ti5": 305, "daynight": "D"}).json()
    assert body["classification"]["category"] in ("industrial", "vegetation")
    assert "nothing is stored" in body["note"]
    answer = client.post("/api/assistant/query", json={"question": "Give me an overview"}).json()
    assert answer["grounding"].startswith("Computed from")


def test_summary_and_facilities_are_consistent(client):
    summary = client.get("/api/stats/summary").json()
    assert summary["totals"]["detections"] == summary["totals"]["industrial_detections"] + summary["totals"]["vegetation_detections"]
    facilities = client.get("/api/facilities").json()["items"]
    assert len(facilities) == 37
    matched = [f for f in facilities if f["osm_element_id"]]
    assert all(f["osm_url"].startswith("https://www.openstreetmap.org/") for f in matched)


def test_alert_funnel_and_focus_regions_are_consistent(client):
    summary = client.get("/api/stats/summary").json()
    funnel = summary["funnel"]
    assert funnel["detections"] == summary["totals"]["detections"]
    assert funnel["locations"] >= funnel["persistent_sources"] == summary["totals"]["persistent_sources"]
    assert funnel["routine_locations"] + funnel["alerting_locations"] + funnel["review_locations"] == funnel["locations"]
    assert funnel["needing_attention"] == sum(summary["open_incidents"].values()) + funnel["review_locations"]
    assert funnel["needing_attention"] < funnel["detections"]
    queue = client.get("/api/reviews/queue").json()
    assert queue["locations"] - queue["with_alerts"] == funnel["review_locations"]  # the queue also lists locations that have alerts
    assert {"gujarat_industrial", "punjab_haryana_farms", "jharia_raniganj"} <= {r["id"] for r in summary["regions"]}
    assert all(r["industrial"] + r["vegetation"] == r["detections"] for r in summary["regions"])
    # Regions count locations to review the way the funnel does (the regions do not overlap).
    assert all(r["review_locations"] <= r["pending_review"] for r in summary["regions"])
    assert sum(r["review_locations"] for r in summary["regions"]) <= funnel["review_locations"]


def test_gis_layers_and_geopackage_download(client, tmp_path):
    info = client.get("/api/gis/layers").json()
    counts = {layer["name"]: layer["features"] for layer in info["layers"]}
    detections = client.get("/api/detections", params={"limit": 1}).json()["total"]
    assert counts["detections"] == detections and counts["facility_locations"] == 37 and counts["osm_industrial_areas"] > 1000
    assert info["store"]["exists"] and info["store"]["last_write"]["error"] is None
    response = client.get("/api/gis/geopackage")
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/geopackage+sqlite3")
    path = tmp_path / "download.gpkg"
    path.write_bytes(response.content)
    connection = sqlite3.connect(path)
    try:
        geometry_types = dict(connection.execute("SELECT table_name, geometry_type_name FROM gpkg_geometry_columns").fetchall())
        assert geometry_types["detections"] == "POINT" and geometry_types["facility_boundaries"] == "MULTIPOLYGON"
        assert connection.execute("SELECT COUNT(*) FROM detections").fetchone()[0] == detections
        incident_columns = {row[1] for row in connection.execute("PRAGMA table_info(incidents)")}
        assert {"reason_codes", "policy_version"} <= incident_columns
    finally:
        connection.close()
    sources = client.get("/api/gis/layers/persistent_sources.geojson").json()
    assert sources["type"] == "FeatureCollection" and len(sources["features"]) == counts["persistent_sources"]
    assert client.get("/api/gis/layers/unknown.geojson").status_code == 404


def test_imagery_evidence_and_wind_are_not_invented_offline(client):
    detection_id = client.get("/api/detections", params={"limit": 1}).json()["items"][0]["detection_id"]
    body = client.get(f"/api/context/imagery-evidence/{detection_id}").json()
    assert body["status"] == "unavailable" and body["supports"] is None
    assert client.get(f"/api/context/imagery-evidence/{detection_id}", params={"refresh": True}).status_code == 401
    assert client.get(f"/api/detections/{detection_id}").json()["imagery_evidence"] is None
    assert client.get(f"/api/context/wind/{detection_id}").json()["status"] == "unavailable"
    assert client.get("/api/context/wind/DOESNOTEXIST").status_code == 404


def test_notification_settings_are_validated(client):
    commander = token(client, "commander", "commander-test")
    assert client.patch("/api/settings", json={"notify_min_severity": "LOW"}, headers=commander).status_code == 422
    assert client.patch("/api/settings", json={"dashboard_url": "ftp://example.in"}, headers=commander).status_code == 422
    ok = client.patch("/api/settings", json={"notify_incidents": True, "notify_min_severity": "CRITICAL", "dashboard_url": "https://sentinel.example.in/"}, headers=commander)
    assert ok.status_code == 200 and ok.json()["settings"]["dashboard_url"] == "https://sentinel.example.in"


def test_analyst_review_is_stored_next_to_the_model_output(client):
    queue = client.get("/api/reviews/queue").json()
    assert queue["locations"] > 0 and queue["items"]
    item = queue["items"][0]
    detection_id = item["detection"]["detection_id"]
    body = {"label": "wildfire", "scope": "location", "note": "Checked the latest Sentinel-2 scene", "evidence": ["satellite_imagery"]}
    assert client.post(f"/api/detections/{detection_id}/reviews", json=body).status_code == 401
    analyst = token(client, "analyst", "analyst-test")
    assert client.post(f"/api/detections/{detection_id}/reviews", json={**body, "label": "volcano"}, headers=analyst).status_code == 422
    assert client.post(f"/api/detections/{detection_id}/reviews", json={**body, "evidence": ["rumour"]}, headers=analyst).status_code == 422
    before = client.get("/api/stats/summary").json()["totals"]

    response = client.post(f"/api/detections/{detection_id}/reviews", json=body, headers=analyst)
    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["reviewer"] == "analyst" and review["group_key"] == item["group_key"]
    assert review["agrees_with_model"] == (item["detection"]["category"] == "vegetation")
    detail = client.get(f"/api/detections/{detection_id}").json()
    assert detail["current_review"]["label"] == "wildfire" and detail["class_code"] == item["detection"]["class_code"]  # model output untouched
    after = client.get("/api/stats/summary").json()["totals"]
    assert after["reviewed_detections"] == before["reviewed_detections"] + item["detections"]
    assert after["verification_pending"] == before["verification_pending"] - item["flagged_detections"]
    assert all(entry["group_key"] != item["group_key"] for entry in client.get("/api/reviews/queue").json()["items"])

    assert client.post(f"/api/detections/{detection_id}/reviews", json={"label": "unsure"}, headers=analyst).status_code == 200
    assert [r["label"] for r in client.get(f"/api/detections/{detection_id}").json()["reviews"][:2]] == ["unsure", "wildfire"]  # added, never overwritten
    rows = csv_rows(client.get("/api/reviews/export.csv").text)
    header = rows[0]
    row = next(r for r in rows[1:] if r[header.index("detection_id")] == detection_id)
    assert row[header.index("label")] == "unsure" and row[header.index("label_source")] == "analyst_review" and "frp_log" in header
    stats = client.get("/api/reviews").json()["stats"]
    assert stats["reviews"] >= 2 and stats["labelled_locations"] >= 1


def test_audit_log_records_human_actions_for_signed_in_users(client):
    assert client.get("/api/audit").status_code == 401
    commander = token(client, "commander", "commander-test")
    assert client.patch("/api/settings", json={"high_intensity_frp_mw": 120}, headers=commander).status_code == 200
    entry = client.get("/api/audit", params={"action": "settings"}, headers=commander).json()["items"][0]
    assert entry["actor"] == "commander" and "high_intensity_frp_mw 100.0 -> 120.0" in entry["summary"]
    assert entry["details"]["alert_policy"]["from"] != entry["details"]["alert_policy"]["to"]
    actions = {e["action"] for e in client.get("/api/audit", params={"limit": 1000}, headers=commander).json()["items"]}
    assert {"auth.sign_in", "auth.sign_in_failed", "settings.update", "incident.status", "review.create", "drill.run", "data.upload"} <= actions
    assert client.patch("/api/settings", json={"high_intensity_frp_mw": 100}, headers=commander).status_code == 200


def test_incidents_carry_reason_codes_and_the_alert_policy(client):
    policy = client.get("/api/settings").json()["alert_policy"]
    opened = [i for i in client.get("/api/incidents", params={"status": "OPEN"}).json()["items"] if not i["is_drill"]]
    assert opened, "the bundled week raises alerts"
    assert all(i["reason_codes"] and i["policy_version"] for i in opened)
    assert policy["version"] in {i["policy_version"] for i in opened}
    assert {code for i in opened for code in i["reason_codes"]} <= set(policy["reason_codes"])


def test_a_fixed_dataset_refuses_sync_uploads_and_drills(client, monkeypatch):
    monkeypatch.setattr(settings, "STATIC_DATASET", True)
    analyst, commander = token(client, "analyst", "analyst-test"), token(client, "commander", "commander-test")
    assert client.post("/api/ingestion/sync", json={}, headers=analyst).status_code == 409
    upload = client.post("/api/detections/upload", files={"file": ("rows.csv", "latitude,longitude", "text/csv")}, headers=analyst)
    assert upload.status_code == 409
    drill = client.post("/api/drills", json={"kind": "industrial_excursion", "facility_id": "IND-STL-002"}, headers=commander)
    assert drill.status_code == 409 and "drills are off" in drill.json()["detail"]
    assert client.get("/api/settings").json()["static_dataset"] is True
