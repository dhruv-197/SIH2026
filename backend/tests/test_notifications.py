"""Webhook notifications: message content and delivery outcomes (no network)."""
import asyncio
import json

import httpx

from app.pipeline.notifications import build_payload, deliver

INCIDENT = {
    "id": 13, "incident_type": "INDUSTRIAL_HIGH_INTENSITY", "severity": "HIGH", "status": "OPEN",
    "title": "Possible industrial fire or emergency flaring - MRPL", "summary": "9 detections totalling 93 MW in one overpass",
    "recommended_action": "Ask the facility operator whether this is planned flaring, an upset or a fire",
    "authorities": ["Facility safety officer"], "facility_id": "IND-REF-008", "detection_id": "D13FFDFB0FB9D3709CC3",
    "latitude": 12.98, "longitude": 74.85, "is_drill": False, "created_at": "2026-09-14T17:08:00+00:00",
}


def test_payload_reads_well_in_chat_tools_and_links_to_the_dashboard():
    payload = build_payload(INCIDENT, {"detection_id": "D13FFDFB0FB9D3709CC3", "frp": 19.31}, "incident.opened", "https://sentinel.example.in/")
    assert payload["event"] == "incident.opened"
    assert payload["text"].startswith("[HIGH] Possible industrial fire or emergency flaring - MRPL")
    assert payload["links"]["incident"] == "https://sentinel.example.in/#/incidents?incident=13"
    assert payload["incident"]["authorities"] == ["Facility safety officer"] and payload["detection"]["frp"] == 19.31
    json.dumps(payload)


def test_drills_are_marked_in_the_message():
    payload = build_payload({**INCIDENT, "is_drill": True}, None, "incident.opened")
    assert "DRILL" in payload["text"] and payload["incident"]["is_drill"] is True and payload["links"] == {}


def test_each_delivery_outcome_is_reported():
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(200 if len(received) == 1 else 500)

    payloads = [build_payload(INCIDENT, None, "incident.opened"), build_payload(INCIDENT, None, "incident.reopened")]
    notes = asyncio.run(deliver("https://hooks.example/thermal", payloads, httpx.MockTransport(handler)))
    assert notes == ["Notification delivered to the webhook (HTTP 200)", "Webhook notification failed (HTTP 500)"]
    assert received[1]["event"] == "incident.reopened"


def test_reason_codes_and_alert_policy_are_sent():
    incident = {**INCIDENT, "reason_codes": ["NEW_HEAT_AT_SITE", "MULTI_PIXEL_CLUSTER"], "policy_version": "2.2+abcd1234"}
    payload = build_payload(incident, None, "incident.opened")
    assert "Reason codes: NEW_HEAT_AT_SITE, MULTI_PIXEL_CLUSTER (alert policy 2.2+abcd1234)" in payload["text"]
    assert payload["incident"]["reason_codes"] == ["NEW_HEAT_AT_SITE", "MULTI_PIXEL_CLUSTER"] and payload["incident"]["policy_version"] == "2.2+abcd1234"
