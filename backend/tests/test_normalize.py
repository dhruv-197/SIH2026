import pytest

from app.pipeline.normalize import RecordValidationError, normalize_record, parse_csv_text, validate_records

VIIRS_ROW = {
    "latitude": "22.36029", "longitude": "69.86394", "bright_ti4": "333.24", "scan": "0.43", "track": "0.43",
    "acq_date": "2026-09-12", "acq_time": "2006", "satellite": "N20", "confidence": "n", "version": "2.0NRT",
    "bright_ti5": "291.64", "frp": "4.21", "daynight": "N",
}
MODIS_ROW = {
    "latitude": "23.7428", "longitude": "86.4182", "brightness": "321.5", "scan": "1.2", "track": "1.1",
    "acq_date": "2026-09-10", "acq_time": "445", "satellite": "A", "confidence": "65", "version": "6.1NRT",
    "bright_t31": "299.1", "frp": "12.4", "daynight": "D",
}


def test_viirs_record_is_normalised():
    record = normalize_record(VIIRS_ROW, "firms_public_nrt")
    assert record["satellite"] == "NOAA-20"
    assert record["instrument"] == "VIIRS"
    assert record["confidence"] == "nominal"
    assert record["acq_datetime"] == "2026-09-12T20:06Z"
    assert record["bright_mir"] == 333.24 and record["bright_tir"] == 291.64
    assert record["detection_id"] == normalize_record(dict(VIIRS_ROW), "other")["detection_id"], "id must be stable"


def test_modis_record_uses_modis_columns_and_numeric_confidence():
    record = normalize_record(MODIS_ROW, "firms_api")
    assert record["instrument"] == "MODIS"
    assert record["satellite"] == "Aqua"
    assert record["confidence"] == "nominal"
    assert record["acq_time"] == "0445"


@pytest.mark.parametrize("field, value, message", [
    ("acq_time", "", "acq_time"),
    ("daynight", "X", "daynight"),
    ("frp", "-1", "frp"),
    ("latitude", "95", "latitude"),
    ("bright_ti4", "abc", "not a number"),
])
def test_invalid_records_are_rejected_not_filled_in(field, value, message):
    row = dict(VIIRS_ROW)
    row[field] = value
    with pytest.raises(RecordValidationError) as exc:
        normalize_record(row, "user_upload")
    assert message in str(exc.value)


def test_validate_records_reports_row_numbers():
    bad = dict(VIIRS_ROW, frp="")
    valid, rejected = validate_records([VIIRS_ROW, bad], "user_upload")
    assert len(valid) == 1
    assert rejected == [{"row": 3, "reason": "missing required field: frp"}]


def test_csv_parsing_handles_bom_and_case():
    text = "﻿LATITUDE,Longitude,bright_ti4,bright_ti5,frp,acq_date,acq_time,daynight\n22.1,70.2,340,295,3.2,2026-09-10,0800,D\n"
    rows = parse_csv_text(text)
    assert rows[0]["latitude"] == "22.1"
    assert normalize_record(rows[0], "user_upload")["instrument"] == "VIIRS"


def test_archive_static_source_flag_is_kept_when_present():
    assert normalize_record(dict(VIIRS_ROW, type="2"), "firms_archive")["firms_type"] == 2
    assert normalize_record(VIIRS_ROW, "firms_public_nrt")["firms_type"] is None
    assert normalize_record(dict(VIIRS_ROW, type="x"), "firms_archive")["firms_type"] is None
