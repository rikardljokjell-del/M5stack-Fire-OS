"""Isolated native Home Assistant integration smoke, with synthetic entities only.

Prepare on a normal Python host with the setup requirements installed:
    python -m home_assistant.ha_runtime_smoke --prepare /tmp/fire-home-ci
Run --inside /config only in the official HA container, on an isolated Docker
network with the generated standard broker named fire-home-mqtt. Never point
this script at an existing HA configuration. No real HA token/account is used.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
import secrets
import ssl
import threading
import time


HOST = "fire-home-mqtt"
PREFIX = "fire/home/v1/ci/fire01"
SLUG = "fire_ci_fire01"
MARKER = "FIRE_HOME_EPHEMERAL_CI_ONLY_V1"


def prepare(directory: Path) -> None:
    """Write a new throwaway configuration; never mutate an existing HA."""
    from .generate import generate

    if directory.exists() and any(directory.iterdir()):
        raise ValueError("CI output must be new or empty")
    directory.mkdir(parents=True, exist_ok=True)
    broker = directory / "broker"
    generate({"site": "ci", "device": "fire01", "local_host": HOST,
              "cards": [
                  {"id": "lamp", "name": "Synthetic lamp", "kind": "switch", "unit": "",
                   "ops": ["on", "off"], "entity": "switch.fire_smoke_lamp"},
                  {"id": "temp", "name": "Synthetic temperature", "kind": "sensor", "unit": "°C",
                   "ops": [], "entity": "sensor.fire_smoke_temp"},
                  {"id": "heat", "name": "Synthetic thermostat", "kind": "climate", "unit": "°C",
                   "ops": ["temperature", "heat_mode"], "entity": "climate.fire_smoke_climate",
                   "min": 10.0, "max": 28.0, "step": 0.5, "modes": ["off", "heat"]},
                  {"id": "run", "name": "Synthetic action", "kind": "script", "unit": "",
                   "ops": ["run"], "entity": "script.fire_smoke_run"},
              ]}, broker)
    ha = directory / "ha"
    packages = ha / "packages"
    packages.mkdir(parents=True)
    (ha / ".fire_home_ci_only").write_text(MARKER, encoding="utf-8")
    # This is the exact generator output, not a test-specific rewrite of its actions.
    (packages / "fire_home.yaml").write_bytes((broker / "fire_home.yaml").read_bytes())
    increment = {"action": "counter.increment", "target": {"entity_id": "counter.fire_smoke_calls"}}
    configuration = {
        "homeassistant": {"name": "FIRE isolated CI", "latitude": 0, "longitude": 0,
                          "elevation": 0, "unit_system": "metric", "time_zone": "UTC"},
        "http": {"server_host": "127.0.0.1", "server_port": 8123},
        "input_boolean": {"fire_smoke_lamp": {"initial": False}, "fire_smoke_heater": {"initial": False}},
        "counter": {"fire_smoke_calls": {"initial": 0, "step": 1, "restore": True}},
        "template": [{
            "switch": [
                {"name": "Fire Smoke Lamp", "unique_id": "fire_smoke_lamp", "default_entity_id": "switch.fire_smoke_lamp",
                 "state": "{{ is_state('input_boolean.fire_smoke_lamp','on') }}",
                 "turn_on": [increment, {"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.fire_smoke_lamp"}}],
                 "turn_off": [increment, {"action": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.fire_smoke_lamp"}}]},
                {"name": "Fire Smoke Heater", "unique_id": "fire_smoke_heater", "default_entity_id": "switch.fire_smoke_heater",
                 "state": "{{ is_state('input_boolean.fire_smoke_heater','on') }}",
                 "turn_on": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.fire_smoke_heater"}}],
                 "turn_off": [{"action": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.fire_smoke_heater"}}]},
            ],
            "sensor": [{"name": "Fire Smoke Temp", "unique_id": "fire_smoke_temp", "default_entity_id": "sensor.fire_smoke_temp", "state": "21.5", "unit_of_measurement": "°C"}],
        }],
        "climate": [{"platform": "generic_thermostat", "name": "Fire Smoke Climate",
                     "unique_id": "fire_smoke_climate", "heater": "switch.fire_smoke_heater",
                     "target_sensor": "sensor.fire_smoke_temp", "min_temp": 10, "max_temp": 28,
                     "target_temp": 20, "initial_hvac_mode": "off", "precision": 0.5}],
        "script": {"fire_smoke_run": {"alias": "Synthetic action", "sequence": [increment]}},
    }
    # Use the actual include mechanism, so native package parsing/merging is tested.
    # JSON flow mappings cannot contain YAML tags. Emit the one tagged block as
    # normal YAML and keep every remaining component as JSON-as-YAML.
    core = configuration.pop("homeassistant")
    text = "homeassistant:\n" + "".join("  " + key + ": " + json.dumps(value) + "\n" for key, value in core.items())
    text += "  packages: !include_dir_named packages\n"
    for key, value in configuration.items():
        text += key + ": " + json.dumps(value, ensure_ascii=False) + "\n"
    (ha / "configuration.yaml").write_text(text, encoding="utf-8")
    credentials = json.loads((broker / "secrets.yaml").read_text(encoding="utf-8"))
    ca = (broker / "certs" / "ca.pem").read_text(encoding="utf-8")
    storage = ha / ".storage"
    storage.mkdir()
    # Only this ephemeral instance is seeded; production HA uses its normal UI.
    entry = {"entry_id": "01FIREHOMECI0000000000000000", "domain": "mqtt", "title": "CI broker",
             "version": 2, "minor_version": 1, "source": "user", "unique_id": None,
             "data": {"broker": HOST, "port": 8883, "username": "fire_ha",
                      "password": credentials["fire_home_fire_ha"], "certificate": ca,
                      "tls_insecure": False, "protocol": "5"},
             "options": {"discovery": False, "birth_message": {}, "will_message": {}},
             "disabled_by": None, "pref_disable_new_entities": False, "pref_disable_polling": False,
             "discovery_keys": {}, "subentries": [],
             "created_at": "2026-01-01T00:00:00+00:00", "modified_at": "2026-01-01T00:00:00+00:00"}
    (storage / "core.config_entries").write_text(json.dumps({"version": 1, "minor_version": 5,
        "key": "core.config_entries", "data": {"entries": [entry]}}), encoding="utf-8")
    (ha / "ci-device.json").write_text(json.dumps({"local_password": credentials["fire_home_fire01_local"],
        "remote_password": credentials["fire_home_fire01_remote"], "ca": ca}), encoding="utf-8")
    print("Prepared isolated HA/broker fixture; no credentials printed")


class Device:
    """Real network client, using only the generated FIRE identity and ACL."""
    def __init__(self, directory: Path, remote: bool):
        import paho.mqtt.client as mqtt

        credentials = json.loads((directory / "ci-device.json").read_text(encoding="utf-8"))
        self.route = "remote" if remote else "local"
        self.messages: list[tuple[float, str, object]] = []
        self.ready = threading.Event()
        self.reason = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fire-ci-" + secrets.token_hex(8), protocol=mqtt.MQTTv5,
                                  transport="websockets" if remote else "tcp")
        self.client.username_pw_set("fire01_" + self.route, credentials[self.route + "_password"])
        if remote:
            self.client.ws_set_options(path="/mqtt")
        else:
            context = ssl.create_default_context(cadata=credentials["ca"])
            self.client.tls_set_context(context)

        def connected(client, userdata, flags, reason, properties):
            self.reason = reason.value
            self.ready.set()

        def message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload)
            except (ValueError, UnicodeDecodeError) as error:
                payload = {"invalid_json": str(error)}
            self.messages.append((time.monotonic(), msg.topic.rsplit("/", 1)[-1], payload))

        self.client.on_connect = connected
        self.client.on_message = message
        self.client.connect(HOST, 9001 if remote else 8883, keepalive=10)
        self.client.loop_start()
        if not self.ready.wait(10) or self.reason != 0:
            self.close()
            raise AssertionError("CI device MQTT connection rejected")
        for suffix in ("catalog", "state", "ack"):
            self.client.subscribe(PREFIX + "/" + self.route + "/" + suffix, qos=1)

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()

    async def send(self, payload, *, retained=False):
        wire = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
        def publish():
            result = self.client.publish(PREFIX + "/" + self.route + "/request", wire, qos=1, retain=retained)
            result.wait_for_publish(10)
            assert result.is_published(), "CI command was not published"
        await asyncio.to_thread(publish)

    async def wait(self, suffix, predicate, *, after=0.0, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for received, kind, value in tuple(self.messages):
                if received >= after and kind == suffix and isinstance(value, dict) and predicate(value):
                    return value
            await asyncio.sleep(.05)
        raise AssertionError("Timed out awaiting " + self.route + " " + suffix)


class PackageErrors(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.errors = []

    def emit(self, record):
        if record.name.startswith(("homeassistant.components.automation", "homeassistant.components.script",
                                   "homeassistant.helpers.template", "homeassistant.helpers.script")):
            self.errors.append(record.getMessage())


async def inside(directory: Path, phase: str):
    """Boot actual HA, parse the actual package and send actual MQTT commands."""
    if (directory / ".fire_home_ci_only").read_text(encoding="utf-8") != MARKER:
        raise ValueError("Refusing a non-CI Home Assistant configuration")
    from homeassistant import bootstrap
    from homeassistant.components import mqtt
    from homeassistant.const import __version__
    from homeassistant.helpers import entity_registry as er, label_registry as lr
    from homeassistant.runner import RuntimeConfig

    errors = PackageErrors()
    logging.getLogger().addHandler(errors)
    checks = []
    hass = None
    local = remote = None

    async def settle():
        await hass.async_block_till_done()
        await asyncio.sleep(.15)

    def calls():
        state = hass.states.get("counter.fire_smoke_calls")
        assert state is not None, "Synthetic counter missing"
        return int(state.state)

    async def catalog(device, predicate=lambda item: True):
        mark = time.monotonic()
        await device.send({"v": 1, "type": "hello", "rid": secrets.token_hex(8)})
        return await device.wait("catalog", lambda item: item.get("epoch") != "0000000000000000" and predicate(item), after=mark)

    async def command(device, card="lamp", op="on", value=None, *, extra=None, retained=False):
        current = await catalog(device)
        packet = {"v": 1, "type": "command", "rid": secrets.token_hex(8), "epoch": current["epoch"],
                  "rev": current["rev"], "seq": current["last_seq"] + 1,
                  "issued": int(time.time()), "ttl": 15, "card": card, "op": op, "value": value}
        if extra:
            packet.update(extra)
        mark = time.monotonic()
        await device.send(packet, retained=retained)
        ack = await device.wait("ack", lambda item: item.get("rid") == packet["rid"], after=mark)
        await settle()
        return packet, ack

    try:
        # The normal bootstrap loads configuration.yaml and its actual packages.
        hass = await bootstrap.async_setup_hass(RuntimeConfig(config_dir=str(directory), skip_pip=True, log_no_color=True))
        assert hass is not None and not hass.config.recovery_mode, "Native HA configuration failed"
        registry = er.async_get(hass)
        labels = lr.async_get(hass)
        read_label = (labels.async_get_label_by_name("fire_home_read") or labels.async_create("fire_home_read")).label_id
        control_label = (labels.async_get_label_by_name("fire_home_control") or labels.async_create("fire_home_control")).label_id
        if phase == "primary":
            for entity in ("switch.fire_smoke_lamp", "sensor.fire_smoke_temp", "climate.fire_smoke_climate", "script.fire_smoke_run"):
                assert registry.async_get(entity) is not None, "Synthetic entity missing from native registry: " + entity
                registry.async_update_entity(entity, labels={read_label, control_label})
        await hass.async_start()
        await settle()
        assert mqtt.is_connected(hass), "Native HA MQTT integration is not connected"
        local = await asyncio.to_thread(Device, directory, False)
        if phase == "restart":
            previous = json.loads((directory / "home-native-primary.json").read_text(encoding="utf-8"))
            restarted = await catalog(local, lambda item: item.get("epoch") != previous["epoch"])
            await asyncio.sleep(1)
            await settle()
            assert calls() == previous["calls"], "Retained command replayed after real HA process restart"
            # A freshly delivered old-epoch request must also fail independently
            # of whether the retained fixture's TTL expired during startup.
            stale, ack = await command(local, "run", "run", extra={"epoch": previous["retained_epoch"]})
            assert ack["status"] == "rejected" and ack["code"] == "session"
            assert calls() == previous["calls"]
            await local.send("", retained=True)
            _, ack = await command(local, "run", "run")
            assert ack["status"] == "executed" and calls() == previous["calls"] + 1
            checks = previous["checks"] + ["real separate-process HA restart rejects retained and fresh old-epoch requests; later valid command works"]
            assert not errors.errors, "Native package error(s): " + " | ".join(errors.errors[:5])
            return {"ok": True, "homeassistant": __version__, "checks": checks,
                    "not_verified": ["physical FIRE and timing/memory", "user's actual HA entities/account",
                                     "Cloudflare public WSS", "power-cut exactly-once physical effects"]}
        remote = await asyncio.to_thread(Device, directory, True)
        initial = await catalog(local, lambda item: len(item.get("cards", [])) == 4)
        assert initial["route"] == "local" and initial["remote_allowed"] is False
        state = await local.wait("state", lambda item: "temp" in item.get("values", {}))
        assert state["values"]["temp"]["value"] == 21.5
        assert state["values"]["heat"]["target"] == 20
        assert state["values"]["heat"]["mode"] == "off"
        assert (await catalog(remote))["cards"] == []
        checks.append("actual HA config/package, labels, native catalog/state and climate metadata")

        before = calls()
        replay, ack = await command(local)
        assert ack["status"] == "executed" and ack["code"] == "ok"
        assert hass.states.is_state("switch.fire_smoke_lamp", "on") and calls() == before + 1
        mark = time.monotonic()
        await local.send(replay)
        ack = await local.wait("ack", lambda item: item.get("rid") == replay["rid"], after=mark)
        await settle()
        assert ack["status"] != "executed" and calls() == before + 1
        checks.append("real MQTT command, real native switch service and duplicate rejection")

        for raw in ("[]", "null", '"text"', "{", '{"v":1,"type":"command"}', '{"v":1,"v":null}'):
            await local.send(raw)
        _, ack = await command(local, "run", "run")
        assert ack["status"] == "executed" and calls() == before + 2
        _, ack = await command(local, "heat", "temperature", 22.5)
        assert ack["status"] == "executed"
        assert hass.states.get("climate.fire_smoke_climate").attributes["temperature"] == 22.5
        _, ack = await command(local, "heat", "temperature", 22.25)
        assert ack["status"] == "rejected" and ack["code"] == "schema"
        assert hass.states.get("climate.fire_smoke_climate").attributes["temperature"] == 22.5
        _, ack = await command(local, "run", "run", extra={"issued": int(time.time()) - 30, "ttl": 1})
        assert ack["status"] == "rejected" and ack["code"] == "expired" and calls() == before + 2
        checks.append("native malformed-input recovery, script dispatch, climate bounds/step and TTL")

        registry.async_update_entity("switch.fire_smoke_lamp", labels={read_label})
        await settle()
        _, ack = await command(local, op="off")
        assert ack["status"] == "rejected" and calls() == before + 2
        registry.async_update_entity("sensor.fire_smoke_temp", labels=set())
        await settle()
        restricted = await catalog(local, lambda item: "temp" not in [card["id"] for card in item["cards"]])
        assert "temp" not in [card["id"] for card in restricted["cards"]]
        mark = time.monotonic()
        await local.send({"v": 1, "type": "hello", "rid": secrets.token_hex(8)})
        await local.wait("state", lambda item: "temp" not in item.get("values", {}), after=mark)
        registry.async_update_entity("switch.fire_smoke_lamp", labels={read_label, control_label})
        checks.append("actual HA label revocation clears retained catalog/state and blocks control")

        await hass.services.async_call("input_boolean", "turn_on", {"entity_id": "input_boolean." + SLUG + "_remote"}, blocking=True)
        await settle()
        await catalog(remote, lambda item: item.get("remote_allowed") is True)
        _, ack = await command(remote, op="off")
        assert ack["status"] == "executed" and calls() == before + 3
        stale_remote = await catalog(remote)
        await hass.services.async_call("input_boolean", "turn_off", {"entity_id": "input_boolean." + SLUG + "_remote"}, blocking=True)
        await settle()
        _, ack = await command(remote, extra={"rev": stale_remote["rev"]})
        assert ack["status"] == "rejected" and calls() == before + 3
        assert (await catalog(remote))["cards"] == []
        checks.append("live remote-off enforcement on existing WebSocket connection")

        retained, ack = await command(local, "run", "run", retained=True)
        assert ack["status"] == "executed" and calls() == before + 4
        old_epoch = retained["epoch"]
        await hass.services.async_call("automation", "reload", {}, blocking=True)
        await settle()
        reloaded = await catalog(local, lambda item: item.get("epoch") != old_epoch)
        assert calls() == before + 4, "Retained command replayed during automation reload"
        checks.append("real automation reload rotates epoch without retained command replay")
        assert not errors.errors, "Native package error(s): " + " | ".join(errors.errors[:5])
        # Workflow starts a NEW container/process with the same native storage.
        # HA async_stop permanently shuts down thread callbacks for this loop;
        # recycling an instance on that loop would not be a genuine restart.
        return {"ok": True, "homeassistant": __version__, "checks": checks,
                "epoch": reloaded["epoch"], "retained_epoch": old_epoch, "calls": before + 4}
    finally:
        if local:
            await asyncio.to_thread(local.close)
        if remote:
            await asyncio.to_thread(remote.close)
        if hass:
            await hass.async_stop(force=True)
        logging.getLogger().removeHandler(errors)


def main():
    parser = argparse.ArgumentParser(description="Isolated native HA CI smoke; never use an existing HA directory")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", type=Path)
    mode.add_argument("--inside", type=Path)
    parser.add_argument("--phase", choices=("primary", "restart"), default="primary")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
        return
    result = asyncio.run(asyncio.wait_for(inside(args.inside, args.phase), timeout=600))
    report = json.dumps(result, ensure_ascii=False, indent=2)
    filename = "home-native-primary.json" if args.phase == "primary" else "home-native-report.json"
    (args.inside / filename).write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
