"""Destructive paths run only against an in-memory 16 MiB flash model."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
from types import ModuleType

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from scripts import migrate_fire as m


def table(rows):
    raw=b"".join(struct.pack("<HBBII16sI",0x50AA,kind,sub,off,size,name.encode().ljust(16,b"\0"),flags)
                 for name,kind,sub,off,size,flags in rows)
    return (raw+b"\xeb\xeb"+b"\xff"*14+hashlib.md5(raw).digest()).ljust(4096,b"\xff")


def image(label):
    data=label.ljust(32,b"\0")
    header=bytearray(24);header[:4]=b"\xe9\x01\x02\x40";header[23]=1
    raw=bytes(header)+struct.pack("<II",0x40080000,len(data))+data
    checksum=0xEF
    for b in data:checksum^=b
    raw=raw+b"\0"*((15-len(raw))%16)+bytes([checksum])
    return raw+hashlib.sha256(raw).digest()


@pytest.fixture
def artifacts(tmp_path):
    folder=tmp_path/"migration";folder.mkdir()
    key=ec.generate_private_key(ec.SECP256R1())
    pem=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    (folder/"release-public.pem").write_bytes(pem)
    files=[]
    for role,(name,offset,maximum) in m.ROLES.items():
        raw=table(m.PARTITIONS) if role=="partitions" else image(role.encode())
        (folder/name).write_bytes(raw)
        files.append(dict(role=role,name=name,offset=offset,max_size=maximum,size=len(raw),sha256=m.sha(raw)))
    manifest=dict(schema=1,target="m5stack-fire",chip="esp32",flash_size=m.FLASH_SIZE,layout="fire-ab-recovery-v1",recovery_version=1,source_commit="a"*40,files=files)
    raw=json.dumps(manifest,sort_keys=True,separators=(",",":")).encode()
    (folder/"migration.json").write_bytes(raw)
    (folder/"migration.sig").write_bytes(base64.b64encode(key.sign(raw,ec.ECDSA(hashes.SHA256()))))
    normal=(folder/"normal.bin").read_bytes()
    payload=dict(schema=2,repository="rikardljokjell-del/M5stack-Fire-OS",target="m5stack-fire",layout="fire-ab-recovery-v1",min_recovery=1,channel="stable",
                 files=[dict(name="fire-test.bin",version="1.2.0",notes="Testpakke",path="firmware/fire-test.bin",published_at="2026-11-24T12:00:00Z",sha256=m.sha(normal),size_bytes=len(normal),source_commit="a"*40)])
    raw=json.dumps(payload,separators=(",",":"),sort_keys=True).encode()
    envelope=dict(schema=2,algorithm="ecdsa-p256-sha256",key_id="fire-release-2026",payload=base64.b64encode(raw).decode(),signature=base64.b64encode(key.sign(raw,ec.ECDSA(hashes.SHA256()))).decode())
    (folder/"catalog-v2.json").write_text(json.dumps(envelope))
    return folder,key,pem,manifest


def resign(folder,key,manifest):
    raw=m.canonical(manifest);(folder/"migration.json").write_bytes(raw)
    (folder/"migration.sig").write_bytes(base64.b64encode(key.sign(raw,ec.ECDSA(hashes.SHA256()))))


def security(**changes):
    return dict(chip="ESP32",flash_size=m.FLASH_SIZE,flash_id=0x1840EF,mac="aabbccddeeff",revision=300,
                secure_boot=False,flash_encryption=False,secure_download=False,fuse0=0,fuse3=0,fuse6=0,**changes)


class Flash:
    def __init__(self):
        self.memory=bytearray(b"\xff"*m.FLASH_SIZE);self.memory[0x8000:0x9000]=table(m.LEGACY)
        self.calls=[];self.info=security();self.corrupt_second=False;self.corrupt_write=False
        self.full_reads=0;self.reset_count=0;self.before_write=None
    def security(self):return copy.deepcopy(self.info)
    def read(self,offset,size):
        self.calls.append(("read",offset,size))
        data=bytes(self.memory[offset:offset+size])
        if offset==0 and size==m.FLASH_SIZE:
            self.full_reads+=1
            if self.corrupt_second and self.full_reads==2:data=b"X"+data[1:]
        return data
    def write(self,offset,data):
        if self.before_write:self.before_write()
        self.calls.append(("write",offset,len(data)))
        self.memory[offset:offset+len(data)]=data
        if self.corrupt_write:self.memory[offset]^=1
    def erase_ota(self):
        self.calls.append(("erase",0xE000,0x2000));self.memory[0xE000:0x10000]=b"\xff"*0x2000
    def reset(self):self.reset_count+=1
    def close(self):pass


def test_valid_bundle_offline_never_opens_serial(artifacts,monkeypatch):
    folder,key,pem,manifest=artifacts
    bundle=m.validate_bundle(folder,pem)
    assert set(bundle.images)==set(m.ROLES)
    monkeypatch.setattr(m,"validate_bundle",lambda folder:bundle)
    monkeypatch.setattr(m,"EsptoolTransport",lambda *_:pytest.fail("Offline validation opened a serial port"))
    assert m.main(["--bundle",str(folder)])==0
    assert m.main(["migrate","--bundle",str(folder),"--port","COM3"])==2


@pytest.mark.parametrize("change",["signature","key","file","offset","size","duplicate","catalog"])
def test_bundle_tampering_fails_closed(artifacts,change):
    folder,key,pem,manifest=artifacts
    if change=="signature":(folder/"migration.sig").write_bytes(b"AAAA")
    elif change=="key":(folder/"release-public.pem").write_bytes(m.PINNED_KEY)
    elif change=="file":(folder/"normal.bin").write_bytes(b"bad")
    elif change=="catalog":(folder/"catalog-v2.json").write_text('{}')
    else:
        if change=="offset":manifest["files"][0]["offset"]=0
        if change=="size":manifest["files"][0]["size"]=True
        if change=="duplicate":manifest["files"][1]=manifest["files"][0]
        resign(folder,key,manifest)
    with pytest.raises(m.MigrationError):m.validate_bundle(folder,pem)


@pytest.mark.parametrize("field,value",[("chip","ESP32-S3"),("flash_size",0x800000),("secure_boot",True),
    ("flash_encryption",True),("secure_download",True),("fuse0",1<<16),("fuse0",1<<20),
    ("fuse6",1<<4),("fuse6",1<<7),("fuse3",1),("fuse6",3),("secure_boot",None)])
def test_incompatible_chip_or_efuses_never_start_backup_or_write(artifacts,tmp_path,field,value):
    folder,key,pem,_=artifacts;bundle=m.validate_bundle(folder,pem);flash=Flash();flash.info[field]=value
    with pytest.raises(m.MigrationError):m.migrate(bundle,flash,tmp_path/"backup")
    assert flash.calls==[]


def test_full_verified_backup_precedes_allowlisted_writes_and_preserves_other_regions(artifacts,tmp_path):
    folder,key,pem,_=artifacts;bundle=m.validate_bundle(folder,pem);flash=Flash()
    flash.memory[0x9000:0xE000]=b"N"*0x5000
    flash.memory[0x650000:0xC90000]=b"A"*0x640000
    flash.memory[0xF90000:0xFC0000]=b"C"*0x30000
    flash.memory[0xFF0000:]=b"D"*0x10000
    original=bytes(flash.memory)
    def check_backup_exists():
        backups=list((tmp_path/"backups").glob("*/backup.json"));assert len(backups)==1
        metadata=json.loads(backups[0].read_text());assert metadata["sha256"]==m.sha(original)
        assert (backups[0].parent/"flash.bin").read_bytes()==original
        assert flash.full_reads==2
    flash.before_write=check_backup_exists
    saved=m.migrate(bundle,flash,tmp_path/"backups")
    assert (saved/"flash.bin").stat().st_size==m.FLASH_SIZE
    assert [x[1] for x in flash.calls if x[0]=="write"]==[0x10000,0xC90000,0x8000,0x1000]
    assert [x for x in flash.calls if x[0]=="erase"]==[("erase",0xE000,0x2000)]
    assert flash.memory[0x9000:0xE000]==original[0x9000:0xE000]
    assert flash.memory[0x650000:0xC90000]==original[0x650000:0xC90000]
    assert flash.memory[0xF90000:0xFC0000]==original[0xF90000:0xFC0000]
    assert flash.memory[0xFF0000:]==original[0xFF0000:]
    assert flash.reset_count==1


def test_backup_readback_mismatch_never_writes(artifacts,tmp_path):
    folder,key,pem,_=artifacts;flash=Flash();flash.corrupt_second=True
    with pytest.raises(m.MigrationError):m.migrate(m.validate_bundle(folder,pem),flash,tmp_path/"backups")
    assert not any(c[0] in {"write","erase"} for c in flash.calls)


def test_write_mismatch_stops_before_bootloader_and_ota_erase(artifacts,tmp_path):
    folder,key,pem,_=artifacts;flash=Flash();flash.corrupt_write=True
    with pytest.raises(m.MigrationError):m.migrate(m.validate_bundle(folder,pem),flash,tmp_path/"backups")
    assert [c[1] for c in flash.calls if c[0]=="write"]==[0x10000]
    assert not any(c[0]=="erase" for c in flash.calls) and flash.reset_count==0


def test_unknown_current_layout_saves_full_backup_but_refuses_migration(artifacts,tmp_path):
    folder,key,pem,_=artifacts;flash=Flash();flash.memory[0x8000:0x9000]=b"\xff"*4096
    with pytest.raises(m.MigrationError):m.migrate(m.validate_bundle(folder,pem),flash,tmp_path/"backups")
    assert list((tmp_path/"backups").glob("*/flash.bin"))
    assert not any(c[0] in {"write","erase"} for c in flash.calls)


def test_restore_same_device_even_after_partial_partition_table_damage(tmp_path):
    flash=Flash();original=bytes(flash.memory);saved,_=m.backup(flash,tmp_path/"backups",flash.info)
    flash.memory[0x8000:0x9000]=b"\0"*4096
    fresh=m.restore(saved,flash,tmp_path/"backups")
    assert fresh!=saved and bytes(flash.memory)==original and flash.reset_count==1


def test_restore_wrong_device_or_tampered_backup_never_writes(tmp_path):
    flash=Flash();saved,_=m.backup(flash,tmp_path/"backups",flash.info)
    flash.info["mac"]="112233445566"
    with pytest.raises(m.MigrationError):m.restore(saved,flash,tmp_path/"backups")
    assert not any(c[0]=="write" for c in flash.calls)
    flash.info["mac"]="aabbccddeeff";(saved/"flash.bin").write_bytes(b"truncated")
    with pytest.raises(m.MigrationError):m.restore(saved,flash,tmp_path/"backups")
    assert not any(c[0]=="write" for c in flash.calls)


def test_partition_md5_overlap_and_target_layout_are_validated():
    assert m.partition_rows(table(m.PARTITIONS))==m.PARTITIONS
    corrupt=bytearray(table(m.PARTITIONS));corrupt[20]^=1
    with pytest.raises(m.MigrationError):m.partition_rows(bytes(corrupt))
    bad=list(m.PARTITIONS);bad[1]=("otadata",1,0,0x9000,0x2000,0)
    with pytest.raises(m.MigrationError):m.partition_rows(table(bad))


def test_pinned_public_key_matches_firmware_source():
    p=m.ROOT.parent/"M5Stack-device"/"certs"/"release-public.pem"
    if p.exists():assert m.public_key(m.PINNED_KEY).public_numbers()==m.public_key(p.read_bytes()).public_numbers()


def test_default_missing_package_and_restore_never_open_port(monkeypatch):
    monkeypatch.setattr(m,"EsptoolTransport",lambda *_:pytest.fail("Unsafe serial access"))
    assert m.main([])==2
    assert m.main(["restore","--port","COM3"])==2


def test_fast_baud_is_selected_once_before_any_flash_read(monkeypatch):
    calls=[]
    class ESP:
        def run_stub(self):calls.append('stub');return self
        def change_baud(self,baud):calls.append(('baud',baud))
        def flash_set_parameters(self,size):calls.append(('size',size))
        def read_flash(self,offset,size,progress_fn=None):calls.append(('read',offset,size));return b'x'*size
    module=ModuleType('esptool');module.__version__='4.5.1'
    cmds=ModuleType('esptool.cmds')
    def detect(port,baud,connect_attempts):calls.append(('detect',baud));return ESP()
    cmds.detect_chip=detect
    monkeypatch.setitem(sys.modules,'esptool',module);monkeypatch.setitem(sys.modules,'esptool.cmds',cmds)
    transport=m.EsptoolTransport('COM3')
    transport.read(0,16);transport.read(16,16)
    assert transport.esp.FLASH_WRITE_SIZE==4096
    assert calls==[('detect',115200),'stub',('baud',921600),('size',m.FLASH_SIZE),('read',0,16),('read',16,16)]


def test_real_adapter_padding_never_overwrites_adjacent_table_or_nvs(monkeypatch):
    class ESP:
        FLASH_WRITE_SIZE=0x4000  # Actual ESP32 stub default, unsafe for table padding.
        def __init__(self):self.memory=bytearray(b'N'*0x10000);self.offset=0;self.blocks=[]
        def run_stub(self):return self
        def change_baud(self,baud):pass
        def flash_set_parameters(self,size):pass
        def flash_begin(self,size,offset):self.offset=offset;return (size+self.FLASH_WRITE_SIZE-1)//self.FLASH_WRITE_SIZE
        def flash_block(self,data,number):
            self.blocks.append((self.offset+number*self.FLASH_WRITE_SIZE,len(data)))
            start=self.offset+number*self.FLASH_WRITE_SIZE;self.memory[start:start+len(data)]=data
        def flash_finish(self,reboot):assert reboot is False
    module=ModuleType('esptool');module.__version__='4.5.1';cmds=ModuleType('esptool.cmds');cmds.detect_chip=lambda *a,**kw:ESP()
    monkeypatch.setitem(sys.modules,'esptool',module);monkeypatch.setitem(sys.modules,'esptool.cmds',cmds)
    transport=m.EsptoolTransport('COM3')
    transport.write(0x8000,b'T'*3072)
    transport.write(0x1000,b'B'*0x6FFF)
    assert transport.esp.blocks==[(0x8000,4096)]+[(0x1000+i*4096,4096) for i in range(7)]
    assert transport.esp.memory[0x9000:]==b'N'*0x7000
    assert transport.esp.memory[0x8000:0x8C00]==b'T'*3072
