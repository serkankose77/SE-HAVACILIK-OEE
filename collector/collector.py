"""MTConnect -> InfluxDB collector for SE Havacilik OEE pipeline.

Polls each Haas machine's MTConnect agent /current endpoint at a configured
interval, parses the MTConnectStreams XML, and writes every DataItem
(Events / Samples / Condition) plus a per-machine reachability marker to
InfluxDB 2.x.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("collector")

INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.environ["INFLUX_TOKEN"]
INFLUX_ORG = os.getenv("INFLUX_ORG", "se-havacilik")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "mtconnect")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "2"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5"))
MACHINES_FILE = Path(os.getenv("MACHINES_FILE", "/app/machines.json"))

MEASUREMENT = "mtconnect"
STATUS_MEASUREMENT = "mtconnect_status"

_shutdown = threading.Event()


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _parse_iso(ts: str | None) -> datetime:
    if not ts:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    v = value.strip()
    if not v or v.upper() == "UNAVAILABLE":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def fetch_current(host: str, port: int) -> bytes | None:
    url = f"http://{host}:{port}/current"
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.content
    except requests.RequestException as e:
        log.warning("fetch %s failed: %s", url, e)
        return None


def parse_streams(xml_bytes: bytes):
    """Yield (category, item_type, attribs, text, component_attrs) tuples."""
    root = ET.fromstring(xml_bytes)
    for device in root.iter():
        if _strip_ns(device.tag) != "DeviceStream":
            continue
        for comp in device:
            if _strip_ns(comp.tag) != "ComponentStream":
                continue
            comp_attrs = comp.attrib
            for cat in comp:
                category = _strip_ns(cat.tag)  # Events | Samples | Condition
                for item in cat:
                    yield category, _strip_ns(item.tag), item.attrib, item.text, comp_attrs


def to_points(machine_id: str, machine: dict, xml_bytes: bytes) -> list[Point]:
    points: list[Point] = []
    try:
        for category, item_type, attrs, text, comp_attrs in parse_streams(xml_bytes):
            ts = _parse_iso(attrs.get("timestamp"))
            name = attrs.get("name") or attrs.get("dataItemId") or item_type
            sub_type = attrs.get("subType") or ""
            comp_name = comp_attrs.get("component") or comp_attrs.get("name") or ""

            point = (
                Point(MEASUREMENT)
                .tag("machine_id", machine_id)
                .tag("machine_name", machine.get("name", machine_id))
                .tag("machine_type", machine.get("type", ""))
                .tag("category", category)
                .tag("item_type", item_type)
                .tag("name", name)
                .tag("component", comp_name)
                .time(ts, WritePrecision.NS)
            )
            if sub_type:
                point.tag("sub_type", sub_type)

            value = (text or "").strip()

            if category == "Samples":
                num = _to_float(value)
                if num is not None:
                    point.field("value", num)
                else:
                    point.field("value_str", value or "UNAVAILABLE")
            elif category == "Condition":
                # The element tag itself is the condition state.
                point.field("state", item_type)
                if value:
                    point.field("value_str", value)
                if attrs.get("type"):
                    point.tag("condition_type", attrs["type"])
            else:  # Events
                point.field("value_str", value or "UNAVAILABLE")

            points.append(point)
    except ET.ParseError as e:
        log.error("xml parse error for %s: %s", machine_id, e)
    return points


def status_point(machine_id: str, machine: dict, reachable: bool) -> Point:
    return (
        Point(STATUS_MEASUREMENT)
        .tag("machine_id", machine_id)
        .tag("machine_name", machine.get("name", machine_id))
        .tag("machine_type", machine.get("type", ""))
        .field("reachable", bool(reachable))
        .time(datetime.now(timezone.utc), WritePrecision.NS)
    )


def load_machines() -> dict:
    if not MACHINES_FILE.exists():
        log.error("machines file not found: %s", MACHINES_FILE)
        sys.exit(1)
    with MACHINES_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def collect_loop(write_api, machines: dict) -> None:
    while not _shutdown.is_set():
        start = time.monotonic()
        for mid, m in machines.items():
            if _shutdown.is_set():
                break
            xml = fetch_current(m["host"], int(m["port"]))
            if xml is None:
                try:
                    write_api.write(
                        bucket=INFLUX_BUCKET,
                        org=INFLUX_ORG,
                        record=status_point(mid, m, reachable=False),
                    )
                except Exception as e:  # noqa: BLE001 - log all write errors
                    log.error("influx write (status/down) failed for %s: %s", mid, e)
                continue

            points = to_points(mid, m, xml)
            points.append(status_point(mid, m, reachable=True))
            try:
                write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
                log.debug("wrote %d points for %s", len(points), mid)
            except Exception as e:  # noqa: BLE001
                log.error("influx write failed for %s: %s", mid, e)

        elapsed = time.monotonic() - start
        sleep = max(0.0, POLL_INTERVAL - elapsed)
        if _shutdown.wait(sleep):
            break


def _signal_handler(signum, _frame):
    log.info("signal %s received, shutting down", signum)
    _shutdown.set()


def main() -> None:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    machines = load_machines()
    log.info(
        "loaded %d machines: %s",
        len(machines),
        ", ".join(f"{k}({v.get('host')}:{v.get('port')})" for k, v in machines.items()),
    )
    log.info("influx target: %s org=%s bucket=%s", INFLUX_URL, INFLUX_ORG, INFLUX_BUCKET)

    with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        log.info("starting poll loop, interval=%.2fs", POLL_INTERVAL)
        collect_loop(write_api, machines)

    log.info("shutdown complete")


if __name__ == "__main__":
    main()
