import json
from pathlib import Path

from fire_backend.contracts import schemas


def test_firmware_schemas_match_the_exported_contract():
    root = Path(__file__).resolve().parents[1] / "contracts"
    for name, schema in schemas().items():
        assert json.loads((root / name).read_text(encoding="utf-8")) == schema
    event = schemas()["device-event-v0.2.schema.json"]
    assert event["properties"]["protocol_version"]["const"] == "0.2"
    assert "event_id" in event["required"]
