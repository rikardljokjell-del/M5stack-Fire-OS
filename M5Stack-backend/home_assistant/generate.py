"""Generate native HA YAML and an isolated standard Mosquitto configuration.

Run from M5Stack-backend: python -m home_assistant.generate --config ... --output ...
JSON is emitted as valid YAML 1.2 so generation needs no YAML-specific runtime.
No generated secret or entity mapping is sent through FIRE Backend.
"""
import argparse
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contract import Card, DeviceProfile, IDENTIFIER


class Mapping(Card):
    entity: str = Field(pattern=r"^(light|switch|climate|sensor|binary_sensor|script|scene)\.[a-z0-9_]+$")

    @model_validator(mode="after")
    def domain_matches(self):
        if self.entity.split(".")[0] != self.kind:
            raise ValueError("Entity domain must match the card kind")
        return self


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    site: str = Field(pattern=IDENTIFIER)
    profile: int = Field(default=0,ge=0,le=1)
    device: str = Field(pattern=IDENTIFIER)
    local_host: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.\-]{0,252}$")
    remote_host: str = Field(default="", pattern=r"^(?:[a-zA-Z0-9][a-zA-Z0-9.\-]{0,252})?$")
    read_label: str = Field(default="fire_home_read", pattern=IDENTIFIER)
    control_label: str = Field(default="fire_home_control", pattern=IDENTIFIER)
    cards: list[Mapping] = Field(max_length=12)
    existing_broker: str = Field(default="", pattern=r"^(?:[a-zA-Z0-9][a-zA-Z0-9.\-]{0,252})?$")
    existing_broker_port: int = Field(default=8883, ge=1, le=65535)

    @model_validator(mode="after")
    def unique_cards(self):
        if len({c.id for c in self.cards}) != len(self.cards):
            raise ValueError("Card IDs must be unique")
        if len({c.entity for c in self.cards}) != len(self.cards):
            raise ValueError("An entity appears only once in a profile")
        return self


def template(value):
    return "{{ " + value + " }}"


POLICY_CARDS = """{% set ns = namespace(cards=[]) %}
{% for c in mapping %}
{% if c.entity in label_entities(read_label) %}
{% set ops = c.ops if c.entity in label_entities(control_label) else [] %}
{% set card = dict(id=c.id,name=c.name,kind=c.kind,unit=c.unit,ops=ops) %}
{% if c.kind == 'climate' %}
{% if 'temperature' in c.ops %}{% set card = dict(card,min=c.min,max=c.max,step=c.step) %}{% endif %}
{% if 'heat_mode' in c.ops %}{% set card = dict(card,modes=c.modes) %}{% endif %}
{% endif %}
{% set ns.cards = ns.cards + [card] %}
{% endif %}
{% endfor %}{{ ns.cards }}"""

STATE_VALUES = """{% set ns = namespace(values={}) %}
{% for c in mapping %}{% if c.id in (cards | map(attribute='id') | list) %}
{% set raw = states(c.entity) %}
{% set st = 'unavailable' if raw == 'unavailable' else 'unknown' if raw == 'unknown' else 'on' if raw == 'on' else 'off' if raw == 'off' else 'ok' %}
{% set value = none %}
{% if c.kind == 'light' %}{% set b = state_attr(c.entity,'brightness') %}{% set value = b if b is integer and 0 <= b <= 255 else none %}
{% elif c.kind in ['switch','binary_sensor'] %}{% set value = (raw == 'on') if raw in ['on','off'] else none %}
{% elif c.kind == 'sensor' %}{% set value = (raw | float) if is_number(raw) else none %}
{% elif c.kind == 'climate' %}{% set t = state_attr(c.entity,'current_temperature') %}{% set value = (t | float) if is_number(t) else none %}
{% endif %}
{% set data = dict(state=st,value=value) %}
{% if c.kind == 'climate' %}
{% set target = state_attr(c.entity,'temperature') %}
{% set mode = raw if raw in ['off','heat','auto'] else 'unknown' %}
{% set data = dict(data,target=(target | float) if is_number(target) else none,mode=mode) %}
{% endif %}
{% set ns.values = dict(ns.values,**{c.id:data}) %}
{% endif %}{% endfor %}{{ ns.values }}"""

VALID_SCHEMA = """{% set keys = ['card','epoch','issued','op','rev','rid','seq','ttl','type','v','value'] %}
{{ m is mapping and (m.keys() | list | sort) == keys and m.v is integer and m.v == 1
and m.type == 'command' and m.rid is string and m.rid | regex_match('^[a-f0-9]{16}$')
and m.epoch is string and m.epoch | regex_match('^[a-f0-9]{16}$')
and m.rev is string and m.rev | regex_match('^[a-f0-9]{8,32}$')
and m.seq is integer and 1 <= m.seq <= 2147483647 and m.issued is integer and m.issued >= 0
and m.ttl is integer and 1 <= m.ttl <= 15
and m.card is string and m.card | regex_match('^[a-z0-9][a-z0-9_-]{0,31}$')
and m.op is string and m.op in ['on','off','brightness','temperature','heat_mode','run'] }}"""

VALID_VALUE = """{{ (m.op in ['on','off','run'] and m.value is none)
or (m.op == 'brightness' and m.value is integer and 0 <= m.value <= 255)
or (m.op == 'temperature' and m.value is number and m.value is not boolean and is_number(m.value)
and selected is mapping and selected.get('min') is number and selected.get('max') is number
and selected.get('step') is number and selected.step > 0 and selected.min <= m.value <= selected.max
and (((m.value - selected.min) / selected.step) - (((m.value - selected.min) / selected.step) | round)) | abs < 0.00001)
or (m.op == 'heat_mode' and m.value is string and m.value in selected.get('modes',[])) }}"""


def package(profile):
    slug = "fire_" + profile.site + "_" + profile.device
    prefix = "fire/home/v1/" + profile.site + "/" + profile.device
    ids = {"epoch": "input_text." + slug + "_epoch", "seq": "input_number." + slug + "_seq",
           "remote": "input_boolean." + slug + "_remote"}
    mapping = [c.model_dump(exclude_none=True) for c in profile.cards]
    common = {"mapping": mapping, "read_label": profile.read_label, "control_label": profile.control_label,
              "epoch_entity": ids["epoch"], "seq_entity": ids["seq"], "remote_entity": ids["remote"], "prefix": prefix}
    policy = [{"variables": common}, {"variables": {"policy_cards": POLICY_CARDS}},
              {"variables": {"epoch": template("states(epoch_entity)"), "remote_allowed": template("is_state(remote_entity,'on')"),
                 "rev": template("sha256((dict(cards=policy_cards,remote_allowed=is_state(remote_entity,'on')) | to_json))[:16]")}}]
    publish_steps = policy + [
        {"condition": "template", "value_template": template("route in ['local','remote']")},
        {"variables": {"cards": template("policy_cards if route == 'local' or remote_allowed else []")}},
        {"variables": {"values": STATE_VALUES}},
        {"action": "mqtt.publish", "data": {"topic": template("prefix ~ '/' ~ route ~ '/catalog'"), "qos": 1, "retain": True,
            "payload": template("dict(v=1,site='"+profile.site+"',device='"+profile.device+"',route=route,epoch=epoch,rev=rev,issued=now().timestamp()|int,ttl=90,last_seq=states(seq_entity)|int(0),remote_allowed=remote_allowed,cards=cards)|to_json")}},
        {"action": "mqtt.publish", "data": {"topic": template("prefix ~ '/' ~ route ~ '/state'"), "qos": 1, "retain": True,
            "payload": template("dict(v=1,epoch=epoch,rev=rev,issued=now().timestamp()|int,ttl=90,values=values)|to_json")}},
    ]
    publish_action = "script." + slug + "_publish"
    refresh = [{"action": publish_action, "data": {"route": r}} for r in ("local", "remote")]
    bootstrap = [
        {"action": "input_text.set_value", "target": {"entity_id": ids["epoch"]}, "data": {"value": template("sha256(now().isoformat() ~ (range(0,65536)|random) ~ (range(0,65536)|random))[:16]")}},
        {"action": "input_number.set_value", "target": {"entity_id": ids["seq"]}, "data": {"value": 0}},
    ] + refresh
    ack_base = {"action": "mqtt.publish", "data": {"topic": template("prefix ~ '/' ~ route ~ '/ack'"), "qos": 1, "retain": False,
        "payload": template("dict(v=1,rid=m.rid,seq=m.seq,status=ack_status,code=ack_code)|to_json")}}
    def rejection(condition, code, status="rejected"):
        return {"if": template(condition), "then": [{"variables": {"ack_status": status, "ack_code": code}}, ack_base,
                 {"action": publish_action, "data": {"route": template("route")}}, {"stop": "Request rejected"}]}

    # Each fixed dispatch entry uses generator-validated targets; never a caller-supplied service or URL.
    choices = []
    for card in profile.cards:
        for op in card.ops:
            if op == "on": action = {"action": card.kind+".turn_on", "target": {"entity_id": card.entity}}
            elif op == "off": action = {"action": card.kind+".turn_off", "target": {"entity_id": card.entity}}
            elif op == "brightness": action = {"action": "light.turn_on", "target": {"entity_id": card.entity}, "data": {"brightness": template("m.value")}}
            elif op == "temperature": action = {"action": "climate.set_temperature", "target": {"entity_id": card.entity}, "data": {"temperature": template("m.value")}}
            elif op == "heat_mode": action = {"action": "climate.set_hvac_mode", "target": {"entity_id": card.entity}, "data": {"hvac_mode": template("m.value")}}
            elif card.kind == "script": action = {"action": card.entity}
            else: action = {"action": "scene.turn_on", "target": {"entity_id": card.entity}}
            choices.append({"conditions": template("m.card == '"+card.id+"' and m.op == '"+op+"'"), "sequence": [action]})
    command_steps = policy + [
        {"variables": {"route": template("trigger.id"), "m": template("trigger.payload | from_json({})")}},
        # UTF-8 byte count via native base64 avoids treating 512 Unicode characters as 512 bytes.
        {"condition": "template", "value_template": template("((trigger.payload|base64_encode|length)*3//4 - (2 if (trigger.payload|base64_encode).endswith('==') else 1 if (trigger.payload|base64_encode).endswith('=') else 0)) <= 512")},
        {"if": template("m is mapping and (m.keys()|list|sort) == ['rid','type','v'] and m.v is integer and m.v == 1 and m.type == 'hello' and m.rid is string and m.rid|regex_match('^[a-f0-9]{16}$')"),
         "then": [{"action": publish_action, "data": {"route": template("route")}}, {"stop": "Hello returned current catalog"}]},
        {"condition": "template", "value_template": VALID_SCHEMA},
        rejection("m.issued > (now().timestamp()|int) + 2 or (now().timestamp()|int) > m.issued + m.ttl", "expired"),
        rejection("epoch == '0000000000000000' or m.epoch != epoch", "session"),
        rejection("m.rev != rev", "revision"),
        rejection("m.seq <= (states(seq_entity)|int(0))", "sequence", "unknown"),
        rejection("route == 'remote' and not remote_allowed", "denied"),
        {"variables": {"selected": template("(mapping | selectattr('id','eq',m.card)|list|first)|default({})")}},
        rejection("selected is not mapping or selected.get('entity','') not in label_entities(read_label) or selected.get('entity','') not in label_entities(control_label) or m.op not in selected.get('ops',[])", "denied"),
        rejection("not ("+VALID_VALUE.replace("{{", "").replace("}}", "")+")", "schema"),
        rejection("states(selected.entity) in ['unknown','unavailable']", "unavailable"),
        # All commands and epoch-reset triggers share this single serial queue.
        {"action": "input_number.set_value", "target": {"entity_id": ids["seq"]}, "data": {"value": template("m.seq")}},
        # These final checks are OUTSIDE choose options. A negative check uses
        # explicit stop, ending the whole automation, so it cannot fall through
        # from an aborted choose option to an 'executed' acknowledgement.
        rejection("states(epoch_entity) != m.epoch", "session"),
        rejection("(now().timestamp()|int) > m.issued + m.ttl", "expired"),
        rejection("route == 'remote' and not is_state(remote_entity,'on')", "denied"),
        rejection("selected.entity not in label_entities(read_label) or selected.entity not in label_entities(control_label)", "denied"),
        # If a service fails, HA stops and FIRE's 10-second ACK timeout becomes unknown.
        # No automatic replay is allowed. Do not emit a premature 'unknown' before success.
        {"choose": choices},
        {"variables": {"ack_status": "executed", "ack_code": "ok"}}, ack_base,
        {"action": publish_action, "data": {"route": template("route")}},
    ]
    # Startup/reset and dispatch run on the same queued automation to serialize sequence state.
    controller = {"id": slug+"_controller", "alias": "FIRE "+profile.site+" sikker styring", "mode": "queued", "max": 8,
      "triggers": [{"trigger": "homeassistant", "event": "start", "id": "bootstrap"},
                   {"trigger": "event", "event_type": "automation_reloaded", "id": "bootstrap"}] +
                  [{"trigger": "mqtt", "topic": prefix+"/"+r+"/request", "qos": 1, "id": r} for r in ("local","remote")],
      "actions": [{"choose": [{"conditions": template("trigger.id == 'bootstrap'"), "sequence": bootstrap}], "default": command_steps}]}
    publisher = {"id": slug+"_refresh", "alias": "FIRE "+profile.site+" status", "mode": "restart",
      "triggers": [{"trigger": "time_pattern", "seconds": "/30"},
                   {"trigger": "state", "entity_id": [c.entity for c in profile.cards]+[ids["remote"]]},
                   {"trigger": "event", "event_type": "entity_registry_updated"},
                   {"trigger": "event", "event_type": "label_registry_updated"}],
      "actions": refresh}
    return {"input_text": {slug+"_epoch": {"name": "FIRE økt", "initial": "0000000000000000", "min": 16, "max": 16}},
      "input_number": {slug+"_seq": {"name": "FIRE sekvens", "min": 0, "max": 2147483647, "step": 1, "mode": "box"}},
      "input_boolean": {slug+"_remote": {"name": "FIRE "+profile.site+" tillat fjernaksess", "icon": "mdi:shield-home"}},
      "script": {slug+"_publish": {"alias": "FIRE publiser begrenset status", "mode": "queued", "max": 4,
                  "fields": {"route": {"description": "local eller remote"}}, "sequence": publish_steps}},
      "automation": [controller, publisher]}


def broker_acl(profile):
    prefix = "fire/home/v1/"+profile.site+"/"+profile.device
    rows = []
    for route in ("local","remote"):
        rows += ["user "+profile.device+"_"+route, "topic write "+prefix+"/"+route+"/request"]
        rows += ["topic read "+prefix+"/"+route+"/"+suffix for suffix in ("catalog","state","ack")]
    rows += ["user fire_ha", "topic read "+prefix+"/+/request"]
    rows += ["topic write "+prefix+"/+/"+suffix for suffix in ("catalog","state","ack")]
    return "\n".join(rows)+"\n"


def broker_config(profile):
    base = """# Standard Mosquitto 2.0.22+; dedicated config, not an overlay on a global auth plugin.
per_listener_settings true
max_packet_size 12288
message_size_limit 8192
max_queued_messages 8
max_queued_bytes 32768
queue_qos0_messages false
max_inflight_messages 4
log_type error
log_type warning
persistence true
persistence_location /mosquitto/data/

# LAN only; certificate SAN must cover the local_host name configured on FIRE.
listener 8883
max_connections 6
allow_zero_length_clientid false
protocol mqtt
allow_anonymous false
password_file /mosquitto/config/passwords.local
acl_file /mosquitto/config/fire.acl
certfile /mosquitto/certs/server.pem
keyfile /mosquitto/certs/server.key
tls_version tlsv1.2

# ONLY a loopback/local connector may access this plain WS origin.
# Docker publishes this listener at 127.0.0.1:9001, never 0.0.0.0.
listener 9001
max_connections 6
allow_zero_length_clientid false
protocol websockets
allow_anonymous false
password_file /mosquitto/config/passwords.remote
acl_file /mosquitto/config/fire.acl
"""
    if profile.existing_broker:
        prefix = "fire/home/v1/"+profile.site+"/"+profile.device
        base += "\n# Bridge to existing HA broker; does not change HA's MQTT integration.\n"
        base += "connection fire-home-bridge\naddress "+profile.existing_broker+":"+str(profile.existing_broker_port)+"\n"
        base += "remote_username fire_home_bridge\nremote_password __SET_FROM_LOCAL_SECRETS__\ncleansession true\nlocal_cleansession true\nkeepalive_interval 10\ntry_private false\nnotifications false\nrestart_timeout 5\nbridge_cafile /mosquitto/certs/ha-broker-ca.pem\nbridge_insecure false\n"
        for route in ("local","remote"):
            base += "topic "+prefix+"/"+route+"/request out 1\n"
            for suffix in ("catalog","state","ack"):
                base += "topic "+prefix+"/"+route+"/"+suffix+" in 1\n"
    return base


def certificates(profile, output):
    """Private local CA; only ca.pem is imported by FIRE/HA, never either key."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    folder=output/"certs";folder.mkdir()
    key=ec.generate_private_key(ec.SECP256R1())
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"FIRE Home local CA")])
    now=datetime.now(timezone.utc)
    ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
        .not_valid_after(now+timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=False,
          data_encipherment=False,key_agreement=False,key_cert_sign=True,crl_sign=True,encipher_only=False,decipher_only=False),critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),critical=False)
        .sign(key,hashes.SHA256()))
    serverkey=ec.generate_private_key(ec.SECP256R1())
    try: san=x509.IPAddress(ipaddress.ip_address(profile.local_host))
    except ValueError: san=x509.DNSName(profile.local_host)
    server=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,profile.local_host)]))
      .issuer_name(name).public_key(serverkey.public_key()).serial_number(x509.random_serial_number())
      .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=365))
      .add_extension(x509.SubjectAlternativeName([san]),critical=False)
      .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
      .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
      .add_extension(x509.SubjectKeyIdentifier.from_public_key(serverkey.public_key()),critical=False)
      .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),critical=False)
      .sign(key,hashes.SHA256()))
    for filename, data in {"ca.pem":ca.public_bytes(serialization.Encoding.PEM),
        "ca-private.key":key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()),
        "server.pem":server.public_bytes(serialization.Encoding.PEM),
        "server.key":serverkey.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())}.items():
        path=folder/filename;path.write_bytes(data)
        try:path.chmod(0o600)
        except OSError:pass


def wizard():
    def ask(label,default=""):
        v=input(label+(" ["+default+"]" if default else "")+": ").strip()
        return v or default
    data={"site":ask("Profil-ID (home/camper)","home"),"device":ask("Enhets-ID","m5stack-fire-01"),
          "local_host":ask("Fast lokal IP eller DNS-navn til Home-brokeren"),
          "remote_host":ask("Eksternt Home-vertsnavn, tomt hvis ikke klart"),"cards":[]}
    data["profile"]=1 if data["site"]=="camper" else 0
    data["existing_broker"]=ask("Eksisterende HA MQTT-broker IP/navn (tomt hvis ingen)")
    if data["existing_broker"]:data["existing_broker_port"]=int(ask("Eksisterende broker TLS-port","8883"))
    print("Legg til opptil 12 kort. Tom entitets-ID avslutter. Ingen passord trengs her.")
    while len(data["cards"])<12:
        entity=ask("HA entitets-ID (f.eks. light.stue)")
        if not entity:break
        kind=entity.split(".")[0]
        ops={"light":["on","off"],"switch":["on","off"],"sensor":[],"binary_sensor":[],"script":["run"],"scene":["run"],"climate":["temperature","heat_mode"]}.get(kind)
        if ops is None:raise ValueError("Støttede typer: light/switch/climate/sensor/binary_sensor/script/scene")
        card={"id":ask("Kort-ID",entity.split(".")[-1][:32]),"entity":entity,"name":ask("Navn på skjermen",entity.split(".")[-1].replace("_"," ")[:32]),"kind":kind,"ops":ops,"unit":ask("Enhet (°C, %, V; tomt ved bryter)")}
        if kind=="light" and ask("Skal dimming tillates? j/n","n").lower()=="j":card["ops"].append("brightness")
        if kind=="climate":card.update(min=float(ask("Laveste tillatte settpunkt","10")),max=float(ask("Høyeste tillatte settpunkt","28")),step=float(ask("Tillatt temperatursteg","0.5")),modes=ask("Tillatte modi, kommaseparert","off,heat").split(","))
        data["cards"].append(card)
    return data


def generate(config, output):
    profile = Profile.model_validate(config)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be new or empty; existing credentials are never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    try: output.chmod(0o700)
    except OSError: pass
    credentials = {profile.device+"_local": secrets.token_urlsafe(32), profile.device+"_remote": secrets.token_urlsafe(32),
                   "fire_ha": secrets.token_urlsafe(32), "fire_home_bridge": secrets.token_urlsafe(32)}
    certificates(profile,output)
    files = {"fire_home.yaml": json.dumps(package(profile),ensure_ascii=False,indent=2)+"\n",
             "fire.acl": broker_acl(profile), "mosquitto.conf": broker_config(profile),
             "passwords.local": "\n".join(k+":"+credentials[k] for k in (profile.device+"_local","fire_ha"))+"\n",
             "passwords.remote": profile.device+"_remote:"+credentials[profile.device+"_remote"]+"\n",
             "secrets.yaml": json.dumps({"fire_home_"+k: v for k,v in credentials.items()},indent=2)+"\n",
             "device-profile.json": json.dumps({"profile":profile.profile,"site":profile.site,"device":profile.device,
                 "local_host":profile.local_host,"local_user":profile.device+"_local","local_password":credentials[profile.device+"_local"],
                 "remote_host":profile.remote_host,"remote_user":profile.device+"_remote","remote_password":credentials[profile.device+"_remote"],
                 "ca":(output/"certs/ca.pem").read_text(encoding="utf-8")},indent=2)+"\n"}
    if profile.existing_broker:
        files["mosquitto.conf"] = files["mosquitto.conf"].replace("__SET_FROM_LOCAL_SECRETS__",credentials["fire_home_bridge"])
        prefix = "fire/home/v1/"+profile.site+"/"+profile.device
        files["existing-broker-acl.txt"] = "user fire_home_bridge\n"+"\n".join(
            ["topic write "+prefix+"/+/request"]+["topic read "+prefix+"/+/"+s for s in ("catalog","state","ack")])+"\n"
    files["hash-passwords.sh"] = "#!/bin/sh\nset -eu\ncd /mosquitto/config\nmosquitto_passwd -U passwords.local\nmosquitto_passwd -U passwords.remote\nchmod 600 passwords.local passwords.remote\n"
    files["compose.yaml"] = json.dumps({"services":{"fire-home-mqtt":{"image":"eclipse-mosquitto:2.1.4-alpine","restart":"unless-stopped",
        "ports":["8883:8883","127.0.0.1:9001:9001"],"volumes":["./:/mosquitto/config:ro","./certs:/mosquitto/certs:ro","fire-home-data:/mosquitto/data"]}},
        "volumes":{"fire-home-data":{}}},indent=2)+"\n"
    files["cloudflared-ingress.yaml"] = json.dumps({"ingress":[{"hostname":profile.remote_host or "home.example.com","service":"http://127.0.0.1:9001"},{"service":"http_status:404"}]},indent=2)+"\n"
    # Keep the local setup upload in exact lockstep with native FireHome::configure.
    DeviceProfile.model_validate_json(files["device-profile.json"])
    for name, content in files.items():
        path=output/name; path.write_text(content,encoding="utf-8")
        try: path.chmod(0o600)
        except OSError: pass
    return profile, sorted(files)


def main():
    parser=argparse.ArgumentParser(description="Lag native HA-oppsett for direkte FIRE Home")
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--config",type=Path)
    choice.add_argument("--wizard",action="store_true")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    profile,files=generate(wizard() if args.wizard else json.loads(args.config.read_text(encoding="utf-8")),args.output)
    print("Oppsett klart for "+profile.site+" / "+profile.device+". Ingen hemmeligheter skrives til terminalen.")
    print("Filer ligger i: "+str(args.output.resolve()))
    print("Les home_assistant/README.md før installasjon. Passordfiler må hashes med mosquitto_passwd -U.")


if __name__=="__main__": main()
