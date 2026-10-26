"""Cloud entry point. Shares the simulator's wire contract; no AWS access on import."""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from iot_ops.validation import validate

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
_TABLE = None


def handler(event, context):
    global _TABLE
    payload = dict(event)
    source_device = payload.pop("source_device_id", None)
    validate(payload)
    if source_device != payload["device_id"]:
        raise ValueError("IoT topic identity does not match telemetry device")
    if payload["device_id"] not in os.environ["DEVICE_IDS"].split(","):
        raise ValueError("Device is not registered in this deployment")
    timestamp = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
    # UTC offsets normalize to one identity; a replay cannot extend retention.
    event_key = f"{timestamp.astimezone(timezone.utc).isoformat()}#{payload['sequence']:020d}"
    item = json.loads(json.dumps(payload, allow_nan=False), parse_float=Decimal)
    item["event_key"] = event_key
    item["expires_at"] = int(timestamp.timestamp()) + int(os.environ.get("RETENTION_DAYS", "7")) * 86400
    if _TABLE is None:
        import boto3
        _TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    try:
        _TABLE.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(device_id) AND attribute_not_exists(event_key)",
        )
    except Exception as error:
        # AWS/Lambda can retry deliveries. A duplicate is successful processing.
        if getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return {"status": "duplicate"}
        raise
    LOG.info("telemetry_processed device_id=%s sequence=%s", payload["device_id"], payload["sequence"])
    return {"status": "stored"}
