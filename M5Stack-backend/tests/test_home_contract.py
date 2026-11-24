"""Home v1 strict wire and generated native-automation behavior.

The runner executes the GENERATED Jinja/choose/condition/action sequence with
fake HA services. This is stronger than string checks, but is not real HA or a
physical broker/device integration test.
"""
import ast
import base64
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

import pytest

from home_assistant.contract import validate_wire, schemas, Catalog, Command, DeviceProfile
from home_assistant.generate import Profile, generate, package, broker_acl, broker_config

ROOT = Path(__file__).resolve().parents[1]
ISOLATED_DEPS = ROOT / "home_assistant/generated/test-deps"
if ISOLATED_DEPS.is_dir():
    sys.path.insert(0, str(ISOLATED_DEPS))

from jinja2 import Environment, StrictUndefined


@pytest.fixture
def config():
    return json.loads((ROOT / "home_assistant/example.json").read_text(encoding="utf-8"))


class Stop(Exception): pass
class ConditionFailed(Exception): pass


class NativeRunner:
    def __init__(self, config):
        self.config = Profile.model_validate(config)
        self.package = package(self.config)
        self.now = 1795500000
        self.states = {c.entity: "on" for c in self.config.cards}
        self.attrs = {c.entity: {"brightness": 128, "current_temperature": 21.5, "temperature": 22}
                      for c in self.config.cards}
        self.states["sensor.stuetemperatur"] = "21.5"
        self.labels = {self.config.read_label: {c.entity for c in self.config.cards},
                       self.config.control_label: {c.entity for c in self.config.cards}}
        slug = "fire_"+self.config.site+"_"+self.config.device
        self.epoch_entity = "input_text."+slug+"_epoch"
        self.seq_entity = "input_number."+slug+"_seq"
        self.remote_entity = "input_boolean."+slug+"_remote"
        self.states.update({self.epoch_entity: "0000000000000000", self.seq_entity: "0", self.remote_entity: "off"})
        self.messages = []
        self.actions = []
        self.before_dispatch = None
        self.env = Environment(undefined=StrictUndefined)
        self.env.filters.update(to_json=lambda v: json.dumps(v,ensure_ascii=False,separators=(",",":"),allow_nan=False),
            from_json=self.from_json, regex_match=lambda v,p: bool(re.match(p,v)),
            base64_encode=lambda v:base64.b64encode(v.encode()).decode())
        self.env.globals.update(states=lambda e:self.states.get(e,"unknown"),
            is_state=lambda e,s:self.states.get(e)==s, state_attr=lambda e,a:self.attrs.get(e,{}).get(a),
            label_entities=lambda label:sorted(self.labels.get(label,set())),
            is_number=lambda v:self.is_number(v), now=lambda:datetime.fromtimestamp(self.now,timezone.utc),
            sha256=lambda v:hashlib.sha256(v.encode()).hexdigest())

    @staticmethod
    def is_number(v):
        try: return not isinstance(v,bool) and math.isfinite(float(v))
        except (ValueError,TypeError): return False

    @staticmethod
    def from_json(v,default=None):
        try: return json.loads(v)
        except (ValueError,TypeError): return default

    def render(self, v, ctx, parse=True):
        if isinstance(v,dict): return {k:self.render(x,ctx) for k,x in v.items()}
        if isinstance(v,list): return [self.render(x,ctx) for x in v]
        if not isinstance(v,str) or ("{{" not in v and "{%" not in v): return v
        text=self.env.from_string(v).render(**ctx).strip()
        if not parse: return text
        try: return ast.literal_eval(text)
        except (ValueError,SyntaxError):
            try: return json.loads(text)
            except ValueError: return text

    def steps(self, steps, ctx):
        for step in steps:
            if "variables" in step:
                for k,v in step["variables"].items(): ctx[k]=self.render(v,ctx)
            elif "condition" in step:
                if not self.render(step["value_template"],ctx): raise ConditionFailed()
            elif "if" in step:
                if self.render(step["if"],ctx): self.block(step["then"],ctx)
            elif "choose" in step:
                for choice in step["choose"]:
                    if self.render(choice["conditions"],ctx):
                        self.block(choice["sequence"],ctx)
                        break
                else: self.block(step.get("default",[]),ctx)
            elif "stop" in step: raise Stop()
            elif "action" in step:
                action=step["action"]
                data=self.render(step.get("data",{}),ctx)
                if action=="mqtt.publish":
                    data["payload"]=self.render(step["data"]["payload"],ctx,parse=False)
                    self.messages.append(data)
                elif action.startswith("script.fire_"):
                    slug=action.removeprefix("script.")
                    try: self.steps(self.package["script"][slug]["sequence"],dict(data))
                    except (Stop,ConditionFailed): pass
                elif action in {"input_text.set_value","input_number.set_value"}:
                    entity=step["target"]["entity_id"]
                    self.states[entity]=str(data["value"])
                    if action=="input_number.set_value" and self.before_dispatch:
                        callback=self.before_dispatch; self.before_dispatch=None; callback()
                else:
                    self.actions.append((action,step.get("target"),data))

    def block(self, steps, ctx):
        # HA condition action failure ends its current sequence block. Explicit
        # stop, unlike condition, propagates to the whole automation/script.
        try:self.steps(steps,ctx)
        except ConditionFailed:pass

    def call(self, trigger):
        try: self.steps(self.package["automation"][0]["actions"],{"trigger":trigger})
        except (Stop,ConditionFailed): pass

    def bootstrap(self): self.call({"id":"bootstrap"})

    def catalog(self, route="local"):
        return json.loads(next(m["payload"] for m in reversed(self.messages) if m["topic"].endswith("/"+route+"/catalog")))

    def command(self, **changes):
        c=self.catalog()
        value={"v":1,"type":"command","rid":"a"*16,"epoch":c["epoch"],"rev":c["rev"],
               "seq":int(self.states[self.seq_entity])+1,"issued":self.now,"ttl":15,
               "card":"desk","op":"on","value":None}
        value.update(changes)
        return value

    def send(self, message, route="local"):
        self.call({"id":route,"payload":json.dumps(message,ensure_ascii=False,separators=(",",":"))})

    def send_raw(self, payload, route="local"):
        self.call({"id":route,"payload":payload})

    def ack(self):
        return json.loads(next(m["payload"] for m in reversed(self.messages) if m["topic"].endswith("/ack")))


def test_generated_schema_is_valid_and_matches_executable_models():
    import jsonschema
    exported=json.loads((ROOT/"contracts/home-v1.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(exported)
    for name,schema in schemas().items():
        schema.pop("$defs",None)
        assert schema==exported["$defs"][name]


@pytest.mark.parametrize("changes",[
    {"value":True,"op":"brightness"},{"ttl":16},{"ttl":True},{"seq":0},
    {"v":True},{"issued":True},{"entity":"light.other"},{"op":"toggle"},
    {"op":"temperature","value":float("nan")},{"op":"on","value":1},
])
def test_strict_command_schema_rejects_bad_types_and_unknown_fields(config,changes):
    run=NativeRunner(config);run.bootstrap();m=run.command(**changes)
    with pytest.raises(ValueError):validate_wire("request",json.dumps(m))


def test_wire_byte_duplicate_and_nonfinite_limits():
    for payload in ('{"v":1,"v":1,"type":"hello","rid":"'+'a'*16+'"}', '{"v":NaN}', 'ø'*257):
        with pytest.raises(ValueError):validate_wire("request",payload)


def test_native_templates_bootstrap_export_only_labelled_cards_and_finite_values(config):
    run=NativeRunner(config);run.labels["fire_home_read"].remove("script.kattedo_trygg_handling")
    run.bootstrap()
    cat=run.catalog()
    assert [c["id"] for c in cat["cards"]]==["desk","heat","room"]
    assert cat["cards"][1]["min"]==10 and cat["cards"][1]["modes"]==["off","heat","auto"]
    assert run.catalog("remote")["cards"]==[]
    for msg in run.messages:
        kind=msg["topic"].rsplit("/",1)[-1]
        validate_wire(kind,msg["payload"])
        assert "light.skrivebord" not in msg["payload"] and "script.kattedo" not in msg["payload"]


def test_native_dispatch_consumes_before_action_and_never_repeats(config):
    run=NativeRunner(config);run.bootstrap();command=run.command()
    run.send(command)
    assert run.actions[0][0]=="light.turn_on" and run.states[run.seq_entity]=="1"
    assert run.ack()["status"]=="executed"
    run.send(command)
    assert len(run.actions)==1 and run.ack()["status"]=="unknown"
    run.bootstrap();run.send(command)
    assert len(run.actions)==1 and run.ack()["code"]=="session"


@pytest.mark.parametrize("change,code",[
    ({"issued":1795499980},"expired"),({"issued":1795500003},"expired"),
    ({"rev":"b"*16},"revision"),({"card":"other"},"denied"),
    ({"op":"brightness","value":True},"schema"),({"op":"brightness","value":256},"schema"),
    ({"card":"heat","op":"temperature","value":28.25},"schema"),
    ({"card":"heat","op":"temperature","value":22.25},"schema"),
    ({"card":"heat","op":"heat_mode","value":"cool"},"schema"),
])
def test_native_action_validation_uses_actual_generated_sequence(config,change,code):
    run=NativeRunner(config);run.bootstrap();run.send(run.command(**change))
    assert not run.actions and run.ack()["code"]==code


def test_native_remote_off_and_live_label_revocation(config):
    run=NativeRunner(config);run.bootstrap();run.send(run.command(),route="remote")
    assert not run.actions and run.ack()["code"]=="denied"
    run.labels["fire_home_control"].clear()
    run.send(run.command())
    assert not run.actions
    # Last-moment revocation AFTER sequence consumption still prevents action.
    run=NativeRunner(config);run.bootstrap()
    run.before_dispatch=lambda:run.labels["fire_home_control"].clear()
    run.send(run.command())
    assert not run.actions and run.states[run.seq_entity]=="1"
    assert run.ack()["status"]=="rejected" and run.ack()["code"]=="denied"


def test_native_hello_and_remote_full_catalog_when_enabled(config):
    run=NativeRunner(config);run.bootstrap()
    run.states[run.remote_entity]="on"
    run.send({"v":1,"type":"hello","rid":"f"*16},route="remote")
    assert len(run.catalog("remote")["cards"])==4
    run.send({"v":1,"type":"hello","rid":"e"*16})
    run.send(run.command(card="heat",op="temperature",value=22.5))
    assert run.actions[-1][0]=="climate.set_temperature"


def test_generator_never_overwrites_credentials_and_separates_auth(config,tmp_path):
    profile,names=generate(config,tmp_path/"out")
    output=tmp_path/"out"
    native=json.loads((output/"fire_home.yaml").read_text())
    assert set(native)=={"input_text","input_number","input_boolean","script","automation"}
    with pytest.raises(ValueError):generate(config,output)
    local=(output/"passwords.local").read_text();remote=(output/"passwords.remote").read_text()
    assert "fire01_remote" not in local and "fire01_local" not in remote and "fire_ha" not in remote
    assert "homeassistant/#" not in (output/"fire.acl").read_text()
    assert "127.0.0.1:9001:9001" in (output/"compose.yaml").read_text()
    assert "backend" not in (output/"mosquitto.conf").read_text().lower()
    device=json.loads((output/"device-profile.json").read_text())
    DeviceProfile.model_validate(device)
    assert set(device)=={"profile","site","device","local_host","remote_host","local_user","local_password","remote_user","remote_password","ca"}
    assert type(device["profile"]) is int and device["profile"]==0
    assert device["ca"]==(output/"certs/ca.pem").read_text()
    from cryptography import x509
    ca=x509.load_pem_x509_certificate(device["ca"].encode())
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert "PRIVATE KEY" not in device["ca"]
    for change in ({"mode":"local"},{"profile":True},{"local_port":8883},{"ca":"-----BEGIN PRIVATE KEY-----bad"}):
        with pytest.raises(ValueError):DeviceProfile.model_validate({**device,**change})


def test_existing_broker_bridge_preserves_other_topics(config):
    profile=Profile.model_validate({**config,"existing_broker":"ha.lan"})
    conf=broker_config(profile)
    assert "cleansession true" in conf and "max_queued_messages 8" in conf
    assert "max_queued_messages 0" not in conf  # Mosquitto: zero means unlimited, not disabled.
    bridge_topics=[line for line in conf.splitlines() if line.startswith("topic ")]
    assert len(bridge_topics)==8
    assert all(line.startswith("topic fire/home/v1/home/fire01/") for line in bridge_topics)
    assert not any(" #" in line for line in bridge_topics)


@pytest.mark.parametrize("payload",[
    "null", "[]", "[1,2]", '"hello"', "17", "true", "{bad json", "{}",
    '{"v":1,"type":"command"}', '{"rid":[],"v":1,"type":"hello"}',
    '{"v":1,"type":"hello","rid":"'+'a'*16+'","extra":1}',
    '{"v":1,"type":"hello","rid":"'+'a'*16+'","rid":[]}',
    '{"v":1,"type":"command","rid":null}', "ø"*257,
])
def test_adversarial_native_payload_does_not_stop_next_valid_command(config,payload):
    run=NativeRunner(config);run.bootstrap();run.send_raw(payload)
    assert not run.actions
    run.send(run.command())
    assert len(run.actions)==1 and run.ack()["status"]=="executed"


def test_native_duplicate_keys_authorize_effective_values_without_replay(config):
    run=NativeRunner(config);run.bootstrap()
    wire=json.dumps(run.command(),separators=(",",":"))
    # Native HA's JSON parser is last-key-wins; invalid effective op cannot dispatch.
    run.send_raw(wire[:-1]+',"op":"toggle"}')
    assert not run.actions
    # An otherwise valid duplicate has no extra authority and still consumes once.
    duplicate=wire[:-1]+',"op":"on"}'
    run.send_raw(duplicate);run.send_raw(duplicate)
    assert len(run.actions)==1 and run.ack()["status"]=="unknown"


@pytest.mark.parametrize("change,code",[("remote","denied"),("expiry","expired"),("epoch","session")])
def test_native_last_moment_rejection_never_falls_through_to_executed_ack(config,change,code):
    run=NativeRunner(config);run.bootstrap();run.states[run.remote_entity]="on"
    run.send({"v":1,"type":"hello","rid":"e"*16})
    command=run.command()
    def revoke():
        if change=="remote":run.states[run.remote_entity]="off"
        elif change=="expiry":run.now+=16
        else:run.states[run.epoch_entity]="b"*16
    run.before_dispatch=revoke
    run.send(command,route="remote")
    assert not run.actions and run.states[run.seq_entity]=="1"
    assert run.ack()["status"]=="rejected" and run.ack()["code"]==code


def test_certificate_renewal_preserves_ca_passwords_and_native_upload(config,tmp_path):
    from cryptography import x509
    from home_assistant.renew_certificate import renew
    out=tmp_path/"generated";generate(config,out)
    keep=["device-profile.json","passwords.local","passwords.remote","secrets.yaml","certs/ca.pem","certs/ca-private.key"]
    before={name:(out/name).read_bytes() for name in keep}
    old=x509.load_pem_x509_certificate((out/"certs/server.pem").read_bytes())
    renew(out)
    assert all((out/name).read_bytes()==body for name,body in before.items())
    new=x509.load_pem_x509_certificate((out/"certs/server.pem").read_bytes())
    assert new.serial_number!=old.serial_number and new.issuer==old.issuer
