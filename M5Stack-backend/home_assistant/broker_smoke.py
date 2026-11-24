"""Real, isolated Mosquitto auth/ACL/TLS smoke. Never contacts the user's HA.

Requires an approved Mosquitto executable and paho-mqtt. Creates random users,
certificates and high localhost ports in a temporary folder, always terminates
the child broker. Does not install a service or change host security settings.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time

from .generate import generate


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]


class Peer:
    def __init__(self,host,port,user,password,*,ca=None,websocket=False):
        import paho.mqtt.client as mqtt
        self.messages=[];self.connected=threading.Event();self.reason=None
        self.client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,protocol=mqtt.MQTTv5,
                                transport="websockets" if websocket else "tcp")
        self.client.username_pw_set(user,password)
        if ca:self.client.tls_set(ca_certs=str(ca),tls_version=ssl.PROTOCOL_TLS_CLIENT)
        if websocket:self.client.ws_set_options(path="/mqtt")
        def on_connect(c,u,flags,reason,props):
            self.reason=reason.value;self.connected.set()
        self.client.on_connect=on_connect
        self.client.on_message=lambda c,u,m:self.messages.append((m.topic,m.payload))
        self.client.connect(host,port,keepalive=10)
        self.client.loop_start()
        if not self.connected.wait(4):
            self.close();raise RuntimeError("MQTT connection timed out")

    def close(self):
        self.client.disconnect();self.client.loop_stop()

    def subscribe(self,topic):
        self.client.subscribe(topic,qos=1);time.sleep(.15)

    def publish(self,topic,payload):
        result=self.client.publish(topic,payload,qos=1,retain=False)
        try:result.wait_for_publish(2)
        except RuntimeError:pass

    def wait(self,topic,payload,timeout=2):
        end=time.monotonic()+timeout
        expected=(topic,payload.encode())
        while time.monotonic()<end:
            if expected in self.messages:return True
            time.sleep(.02)
        return False


def smoke(executable):
    executable=Path(executable).resolve()
    passwd=shutil.which("mosquitto_passwd") or str(executable.with_name("mosquitto_passwd.exe" if os.name=="nt" else "mosquitto_passwd"))
    peers=[]
    process=None
    with tempfile.TemporaryDirectory(prefix="fire-home-broker-") as temporary:
        folder=Path(temporary)
        generate({"site":"smoke","device":"fire01","local_host":"127.0.0.1","cards":[]},folder/"config")
        config=folder/"config"
        creds=json.loads((config/"secrets.yaml").read_text())
        for name in ("passwords.local","passwords.remote"):
            subprocess.run([passwd,"-U",str(config/name)],check=True,capture_output=True,
                           **({"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {}))
        port,remote=free_port(),free_port()
        data=folder/"data";data.mkdir()
        conf=(config/"mosquitto.conf").read_text()
        conf=conf.replace("/mosquitto/config/",config.as_posix()+"/").replace("/mosquitto/certs/",(config/"certs").as_posix()+"/")
        conf=conf.replace("/mosquitto/data/",data.as_posix()+"/")
        conf=conf.replace("listener 8883","listener "+str(port)+" 127.0.0.1").replace("listener 9001","listener "+str(remote)+" 127.0.0.1")
        (config/"smoke.conf").write_text(conf)
        # Probe user exists ONLY in this temporary broker, never generated deployment files.
        probe_password="temporary-probe-"+os.urandom(16).hex()
        with (config/"passwords.local").open("a") as f:f.write("fire_probe:"+probe_password+"\n")
        # Hash only the freshly added plaintext line by creating a separate temporary file.
        probe_file=config/"probe.password";probe_file.write_text("fire_probe:"+probe_password+"\n")
        subprocess.run([passwd,"-U",str(probe_file)],check=True,capture_output=True)
        lines=(config/"passwords.local").read_text().splitlines()
        lines=[line for line in lines if not line.startswith("fire_probe:")]
        (config/"passwords.local").write_text("\n".join(lines)+"\n"+probe_file.read_text())
        with (config/"fire.acl").open("a") as f:f.write("user fire_probe\ntopic readwrite #\n")
        log=(folder/"broker.log").open("w+")
        try:
            process=subprocess.Popen([str(executable),"-c",str(config/"smoke.conf")],stdout=log,stderr=log,
                   **({"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {}))
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise RuntimeError("Broker exited before ready; exit="+str(process.returncode)+". Check OS application-control or broker installation.")
                try:
                    with socket.create_connection(("127.0.0.1",port),timeout=.1):break
                except OSError:time.sleep(.05)
            ca=config/"certs/ca.pem"
            def peer(user,remote_route=False,password=None):
                p=Peer("127.0.0.1",remote if remote_route else port,user,password or creds["fire_home_"+user],ca=None if remote_route else ca,websocket=remote_route)
                peers.append(p);return p
            local=peer("fire01_local");net=peer("fire01_remote",True);ha=peer("fire_ha")
            assert all(p.reason==0 for p in (local,net,ha)),"Allowed users rejected"
            assert peer("fire01_local",True).reason!=0,"Local credential accepted on public listener"
            assert peer("fire01_remote").reason!=0,"Remote credential accepted on LAN listener"
            probe=peer("fire_probe",password=probe_password)
            prefix="fire/home/v1/smoke/fire01/"
            ha.subscribe(prefix+"local/request")
            local.publish(prefix+"local/request","hello-local")
            assert ha.wait(prefix+"local/request","hello-local"),"Authorized request not forwarded"
            local.subscribe(prefix+"local/state");net.subscribe(prefix+"remote/state")
            ha.publish(prefix+"local/state","valid-local")
            assert local.wait(prefix+"local/state","valid-local"),"Authorized state not delivered"
            local.close();net.close()

            # Each negative ACL check uses fresh clients and proves its allowed
            # path first. A prior denied publish must not leave a disconnected
            # client that makes a later negative assertion pass accidentally.
            writer=peer("fire01_local");observer=peer("fire01_local")
            observer.subscribe(prefix+"local/state")
            writer.publish(prefix+"local/request","before-forged-state")
            assert ha.wait(prefix+"local/request","before-forged-state"),"State-forgery writer is not connected"
            ha.publish(prefix+"local/state","before-forged-state")
            assert observer.wait(prefix+"local/state","before-forged-state"),"State-forgery observer is not connected"
            writer.publish(prefix+"local/state","forged-state")
            assert not observer.wait(prefix+"local/state","forged-state",.5),"Device forged state"
            writer.close();observer.close()

            remote_writer=peer("fire01_remote",True)
            ha.subscribe(prefix+"remote/request")
            remote_writer.publish(prefix+"remote/request","before-remote-bypass")
            assert ha.wait(prefix+"remote/request","before-remote-bypass"),"Remote writer is not connected"
            probe.publish(prefix+"local/request","before-remote-bypass")
            assert ha.wait(prefix+"local/request","before-remote-bypass"),"Local-route observer is not connected"
            remote_writer.publish(prefix+"local/request","remote-bypass")
            assert not ha.wait(prefix+"local/request","remote-bypass",.5),"Remote user reached local route"
            remote_writer.close()

            reader=peer("fire01_local")
            reader.subscribe(prefix+"local/state");reader.subscribe("homeassistant/#")
            ha.publish(prefix+"local/state","before-private-state")
            assert reader.wait(prefix+"local/state","before-private-state"),"Private-topic reader is not connected"
            probe.subscribe("homeassistant/probe/state")
            probe.publish("homeassistant/probe/state","private-state")
            assert probe.wait("homeassistant/probe/state","private-state"),"Private-topic positive control was not delivered"
            assert not reader.wait("homeassistant/probe/state","private-state",.5),"Device reads general HA topics"
            reader.close()
            return {"ok":True,"broker":str(executable),"checks":["LAN TLS certificate/name","remote WebSocket origin","listener password separation","exact request/state ACL","no forged state","no remote/local route crossover","no general HA topic access"],
                    "not_verified":["real Home Assistant execution","Cloudflare public WSS certificate/routing","physical FIRE and its memory","HA-label revocation"]}
        finally:
            for p in peers:
                try:p.close()
                except Exception:pass
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            log.close()


def main():
    parser=argparse.ArgumentParser(description="Test isolert ekte Mosquitto, uten å endre HA")
    parser.add_argument("--broker-exe",required=True)
    args=parser.parse_args()
    try:result=smoke(args.broker_exe)
    except Exception as error:
        print(json.dumps({"ok":False,"error":str(error)},ensure_ascii=False));raise SystemExit(1)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
