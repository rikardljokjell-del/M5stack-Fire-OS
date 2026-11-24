"""Deliberate USB migration utility. Never called by the backend or AI.

Default: verify a signed bundle offline. No serial access until preflight,
migrate or restore is explicitly selected. Never burns eFuses or uses --force.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
import unicodedata
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

FLASH_SIZE = 0x1000000
ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / "workspace" / "migration_backups"
PINNED_KEY = b"""-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE94nqcD827cR5L3Fu19qgVUdLzN7O
08K9TBcJ9FkfnLPy3ypPa+GgdvpnelZUfx36EZ3ahvxu5pBF1raifSA9fg==
-----END PUBLIC KEY-----
"""
ROLES = {"bootloader": ("bootloader.bin", 0x1000, 0x7000),
         "partitions": ("partitions.bin", 0x8000, 0x1000),
         "normal": ("normal.bin", 0x10000, 0x640000),
         "recovery": ("recovery.bin", 0xC90000, 0x300000)}
COMMON = [("nvs",1,2,0x9000,0x5000,0), ("otadata",1,0,0xE000,0x2000,0),
          ("app0",0,16,0x10000,0x640000,0), ("app1",0,17,0x650000,0x640000,0)]
PARTITIONS = COMMON + [("recovery",0,0,0xC90000,0x300000,0),
    ("homecfg",1,2,0xF90000,0x20000,0), ("rescuecfg",1,2,0xFB0000,0x10000,0),
    ("coredump",1,3,0xFF0000,0x10000,0)]
LEGACY = COMMON + [("spiffs",1,130,0xC90000,0x360000,0), ("coredump",1,3,0xFF0000,0x10000,0)]


class MigrationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise MigrationError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    text=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    require(unicodedata.normalize("NFC",text)==text,"Signert tekst må være NFC-normalisert.")
    return text.encode("utf-8")


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "JSON-filen har dupliserte felter.")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(MigrationError("Ugyldig tall i JSON.")))
    except (UnicodeError, json.JSONDecodeError):
        raise MigrationError("Kan ikke lese konfigurasjonsfilen.") from None


def read_file(folder, name, limit):
    path = folder / name
    require(path.is_file() and not path.is_symlink() and path.resolve().parent == folder.resolve(),
            "Pakken mangler en vanlig fil: " + name)
    require(path.stat().st_size <= limit, "Filen er for stor: " + name)
    return path.read_bytes()


def public_key(pem):
    try:
        key = serialization.load_pem_public_key(pem)
        require(isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1),
                "Utgivernøkkelen må være P-256.")
        return key
    except (ValueError, TypeError):
        raise MigrationError("Ugyldig offentlig utgivernøkkel.") from None


def verify_signature(key, signature, raw):
    try:
        decoded = base64.b64decode(signature.strip(), validate=True)
        require(8 <= len(decoded) <= 80, "Ugyldig signaturlengde.")
        key.verify(decoded, raw, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        raise MigrationError("Signaturen stemmer ikke med den fastlagte utgivernøkkelen.") from None


def partition_rows(data):
    require(len(data) in (0xC00, 0x1000), "Partisjonstabellen har feil størrelse.")
    rows, marker = [], None
    for offset in range(0, len(data), 32):
        entry = data[offset:offset+32]
        if entry[:2] == b"\xeb\xeb":
            require(marker is None and entry[2:16] == b"\xff"*14, "Ugyldig MD5-post i partisjonstabellen.")
            require(entry[16:] == hashlib.md5(data[:offset]).digest(), "Partisjonstabellens MD5 stemmer ikke.")
            marker = offset
            require(data[offset+32:] == b"\xff" * (len(data)-offset-32), "Uventede data etter partisjonstabellen.")
            break
        require(entry[:2] == b"\xaa\x50", "Partisjonstabellen mangler gyldig MD5-avslutning.")
        magic, kind, subtype, address, size, label, flags = struct.unpack("<HBBII16sI", entry)
        try:
            name = label.split(b"\0",1)[0].decode("ascii")
        except UnicodeError:
            raise MigrationError("Partisjonstabellen har ugyldig navn.") from None
        require(address >= 0x9000 and size > 0 and address+size <= FLASH_SIZE and flags == 0,
                "Partisjonstabellen har ugyldige grenser eller krypteringsflagg.")
        require(not any(address < old[3]+old[4] and old[3] < address+size for old in rows),
                "Partisjonene overlapper.")
        rows.append((name,kind,subtype,address,size,flags))
    require(marker is not None, "Partisjonstabellen mangler MD5-kontroll.")
    return rows


def image_info(data):
    require(len(data) >= 48 and data[0] == 0xE9 and 1 <= data[1] <= 16, "Filen er ikke et gyldig ESP32-bilde.")
    require(data[12:14] == b"\0\0" and data[23] == 1, "Bildet må være ESP32 med innebygd SHA256.")
    require(data[2] == 2 and data[3] == 0x40, "Bildet må være bygget for DIO, 40 MHz og 16 MiB.")
    offset, checksum = 24, 0xEF
    for _ in range(data[1]):
        require(offset+8 <= len(data), "Avkortet bildesegment.")
        address, size = struct.unpack_from("<II", data, offset)
        offset += 8
        require(size > 0 and size <= 0x400000 and offset+size <= len(data), "Ugyldig bildesegment.")
        for value in data[offset:offset+size]: checksum ^= value
        offset += size
    checksum_offset = (offset + 15) // 16 * 16 - 1
    if checksum_offset < offset: checksum_offset += 16
    require(checksum_offset+33 == len(data), "Uventet bildelengde eller signaturtype.")
    require(data[checksum_offset] == checksum, "ESP32-bildets kontrollsum stemmer ikke.")
    require(hashlib.sha256(data[:checksum_offset+1]).digest() == data[checksum_offset+1:], "ESP32-bildets SHA256 stemmer ikke.")
    return {"min_revision": struct.unpack_from("<H",data,15)[0] or data[14]*100,
            "max_revision": struct.unpack_from("<H",data,17)[0] or 65535}


@dataclass
class Bundle:
    manifest: dict
    images: dict[str, bytes]
    revisions: dict[str, dict]


def validate_bundle(directory, trusted_pem=PINNED_KEY):
    directory = Path(directory).resolve()
    require(directory.is_dir(), "Velg en ferdig migrasjonspakke.")
    key = public_key(trusted_pem)
    supplied = public_key(read_file(directory,"release-public.pem",4096))
    require(key.public_numbers() == supplied.public_numbers(), "Pakken forsøker å bytte ut den fastlagte utgivernøkkelen.")
    raw = read_file(directory,"migration.json",32768)
    verify_signature(key, read_file(directory,"migration.sig",512), raw)
    manifest = strict_json(raw)
    require(canonical(manifest)==raw,"Migrasjonsplanen må bruke eksakte kanoniske JSON-byte uten linjeskift.")
    require(isinstance(manifest,dict) and set(manifest) == {"schema","target","chip","flash_size","layout","recovery_version","source_commit","files"}, "Uventede felt i migrasjonsplanen.")
    require((manifest["schema"],manifest["target"],manifest["chip"],manifest["flash_size"],manifest["layout"],manifest["recovery_version"]) ==
            (1,"m5stack-fire","esp32",FLASH_SIZE,"fire-ab-recovery-v1",1), "Migrasjonspakken er ikke for denne FIRE-layouten.")
    require(type(manifest["schema"]) is int and type(manifest["recovery_version"]) is int and type(manifest["flash_size"]) is int,
            "Ugyldige felttyper i migrasjonsplanen.")
    require(isinstance(manifest["source_commit"],str) and re.fullmatch(r"[a-f0-9]{40}",manifest["source_commit"]), "Pakken mangler gyldig kildeversjon.")
    files = manifest["files"]
    require(isinstance(files,list) and len(files)==4, "Pakken må inneholde nøyaktig fire bilder.")
    images, revisions = {}, {}
    for item in files:
        require(isinstance(item,dict) and set(item)=={"role","name","offset","max_size","size","sha256"}, "Uventet filbeskrivelse.")
        role = item["role"]
        require(isinstance(role,str) and role in ROLES and role not in images, "Ukjent eller duplisert filrolle.")
        require((item["name"],item["offset"],item["max_size"]) == ROLES[role], "Pakken forsøker å endre filnavn eller skriveområde.")
        require(all(type(item[k]) is int for k in ("offset","max_size","size")) and 0 < item["size"] <= item["max_size"], "Ugyldig bildestørrelse.")
        require(isinstance(item["sha256"],str) and re.fullmatch(r"[a-f0-9]{64}",item["sha256"]), "Ugyldig filhash.")
        data = read_file(directory,item["name"],item["max_size"])
        require(len(data)==item["size"] and sha(data)==item["sha256"], "En fil er endret eller ufullstendig: "+item["name"])
        if role=="partitions": require(partition_rows(data)==PARTITIONS, "Partisjonstabellen avviker fra fire-ab-recovery-v1.")
        else: revisions[role]=image_info(data)
        images[role]=data
    envelope = strict_json(read_file(directory,"catalog-v2.json",32768))
    require(isinstance(envelope,dict) and set(envelope)=={"schema","algorithm","key_id","payload","signature"}, "Ugyldig firmwarekatalog.")
    require((envelope["schema"],envelope["algorithm"],envelope["key_id"])==(2,"ecdsa-p256-sha256","fire-release-2026"), "Ukjent katalogsignatur.")
    try: payload_raw=base64.b64decode(envelope["payload"],validate=True)
    except (ValueError,TypeError): raise MigrationError("Ugyldig kataloginnhold.") from None
    require(len(payload_raw)<=16384,"Firmwarekatalogen er for stor.")
    verify_signature(key,envelope["signature"],payload_raw)
    payload = strict_json(payload_raw)
    require(canonical(payload)==payload_raw,"Firmwarekatalogen er ikke kanonisk.")
    require(isinstance(payload,dict) and set(payload)=={"schema","repository","target","layout","min_recovery","channel","files"}
            and payload.get("target")=="m5stack-fire" and payload.get("repository")=="rikardljokjell-del/M5stack-Fire-OS"
            and payload.get("schema")==2 and payload.get("layout")=="fire-ab-recovery-v1" and payload.get("min_recovery")==1
            and payload.get("channel")=="stable", "Firmwarekatalogen har feil mål eller layout.")
    entries=payload.get("files")
    require(isinstance(entries,list) and 1<=len(entries)<=8, "Ugyldig firmwareliste.")
    names=set()
    for entry in entries:
        require(isinstance(entry,dict) and set(entry)=={"name","version","notes","path","published_at","sha256","size_bytes","source_commit"},"Ugyldig katalogoppføring.")
        name=entry['name']
        require(isinstance(name,str) and re.fullmatch(r"fire-[A-Za-z0-9_.-]+\.bin",name) and len(name)<=64 and '..' not in name and name not in names,"Ugyldig eller duplisert firmwarenavn.")
        names.add(name)
        require(entry['path']=='firmware/'+name and type(entry['size_bytes']) is int and 0<entry['size_bytes']<=4194304,"Ugyldig firmwaresti eller størrelse.")
        require(isinstance(entry['sha256'],str) and re.fullmatch(r'[a-f0-9]{64}',entry['sha256']) and isinstance(entry['source_commit'],str) and re.fullmatch(r'[a-f0-9]{40}',entry['source_commit']),"Ugyldig firmwarehash/kildeversjon.")
        require(isinstance(entry['version'],str) and entry['version'].isascii() and 1<=len(entry['version'])<=40
                and isinstance(entry['notes'],str) and len(entry['notes'].encode())<=240
                and isinstance(entry['published_at'],str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',entry['published_at']),"Ugyldig firmwaretekst eller dato.")
    matches=[r for r in entries if isinstance(r,dict) and r.get("sha256")==sha(images["normal"]) and r.get("size_bytes")==len(images["normal"])
             and r.get("source_commit")==manifest["source_commit"]]
    require(len(matches)==1, "Normalbildet finnes ikke entydig i den signerte firmwarekatalogen.")
    return Bundle(manifest, images, revisions)


class EsptoolTransport:
    """Pinned 4.5.x API. No serial import/port access in offline check mode."""
    def __init__(self, port, baud=921600):
        require(bool(re.fullmatch(r"COM[1-9][0-9]*",port or "",re.I)) or bool(re.fullmatch(r"/dev/(ttyUSB|ttyACM)[0-9]+",port or "")), "Velg en konkret serieport, for eksempel COM3.")
        require(type(baud) is int and baud in (115200,460800,921600),"Velg støttet overføringshastighet.")
        try:
            import esptool
            require(re.fullmatch(r"4\.5\.[0-9]+",esptool.__version__), "Verktøyet krever esptool 4.5.x.")
            from esptool.cmds import detect_chip
        except ImportError:
            raise MigrationError("Installer requirements-migration.txt før du bruker serieporten.") from None
        self.esp=detect_chip(port,baud=115200,connect_attempts=3)
        self.baud=baud
        self.stub=False

    def security(self):
        e=self.esp
        require(e.CHIP_NAME=="ESP32", "Enheten er ikke en klassisk ESP32.")
        if not self.stub:e.flash_spi_attach(0)
        flash_id=e.flash_id()
        return {"chip":e.CHIP_NAME,"flash_size":1<<((flash_id>>16)&0xFF) if ((flash_id>>16)&0xFF)<32 else 0,
                "flash_id":flash_id,"mac":bytes(e.read_mac()).hex(),"revision":e.get_chip_revision(),
                "secure_boot":bool(e.get_secure_boot_enabled()),"flash_encryption":bool(e.get_flash_encryption_enabled()),
                "secure_download":bool(e.secure_download_mode), "fuse0":e.read_efuse(0),"fuse3":e.read_efuse(3),"fuse6":e.read_efuse(6)}

    def prepare(self):
        if not self.stub:
            self.esp=self.esp.run_stub();self.stub=True
            # The ESP32 stub defaults to 16 KiB blocks. Padding a 3 KiB table
            # to that block would overwrite adjacent NVS at 0x9000. A 4 KiB
            # block is within the stub maximum and every allowed boundary.
            self.esp.FLASH_WRITE_SIZE=0x1000
            if self.baud!=115200:self.esp.change_baud(self.baud)
            self.esp.flash_set_parameters(FLASH_SIZE)

    def read(self, offset, size):
        self.prepare()
        last=[-1]
        def progress(done,total):
            bucket=min(10,done*10//max(total,1))
            if bucket!=last[0]:
                last[0]=bucket;print(f"Leser flash: {bucket*10} %",flush=True)
        return self.esp.read_flash(offset,size,progress_fn=progress if size>=0x100000 else None)

    def write(self, offset, data):
        self.prepare()
        count=self.esp.flash_begin(len(data),offset)
        width=self.esp.FLASH_WRITE_SIZE
        last=-1
        for number in range(count):
            block=data[number*width:(number+1)*width].ljust(width,b"\xff")
            self.esp.flash_block(block,number)
            bucket=(number+1)*10//max(count,1)
            if len(data)>=0x100000 and bucket!=last:
                last=bucket;print(f"Skriver bilde: {bucket*10} %",flush=True)
        self.esp.flash_finish(reboot=False)

    def erase_ota(self):
        self.prepare();self.esp.erase_region(0xE000,0x2000)

    def reset(self): self.esp.hard_reset()
    def close(self): self.esp._port.close()


def check_security(info, bundle=None):
    fields={"chip","flash_size","flash_id","mac","revision","secure_boot","flash_encryption","secure_download","fuse0","fuse3","fuse6"}
    require(set(info)==fields and info["chip"]=="ESP32" and info["flash_size"]==FLASH_SIZE, "Krever klassisk ESP32 med verifisert 16 MiB flash.")
    require(all(type(info[k]) is bool for k in ("secure_boot","flash_encryption","secure_download")) and
            not any(info[k] for k in ("secure_boot","flash_encryption","secure_download")), "Secure Boot eller flashkryptering er aktiv/ukjent. Ingen skriving tillates.")
    require(all(type(info[k]) is int and 0<=info[k]<=0xFFFFFFFF for k in ("fuse0","fuse3","fuse6","flash_id","revision")), "Sikkerhetskontrollen kunne ikke lese eFuses.")
    require(not (info["fuse0"] & ((0xF<<16)|(0x7F<<20))) and not (info["fuse6"] & ((3<<4)|(7<<7)))
            and (info["fuse6"]&3) in (0,1) and not (info["fuse3"]&1), "eFuse-oppsettet er ikke kompatibelt med trygg FIRE-migrering.")
    require(isinstance(info["mac"],str) and re.fullmatch(r"[a-f0-9]{12}",info["mac"]), "Enhetens identitet kunne ikke verifiseres.")
    if bundle:
        for bounds in bundle.revisions.values():
            require(bounds["min_revision"]<=info["revision"]<=bounds["max_revision"], "Et bilde støtter ikke denne ESP32-revisjonen.")


def backup(transport, destination, info):
    destination=Path(destination).resolve()
    repo=ROOT.parent
    require(not destination.is_relative_to(repo) or destination.is_relative_to(BACKUPS.resolve()), "Backup inne i repoet må ligge i ignorert workspace/migration_backups.")
    require(destination.is_relative_to(BACKUPS.resolve()) or not any((ancestor/".git").exists() for ancestor in (destination,*destination.parents)),
            "Legg backup utenfor andre Git-repoer, eller bruk standardmappen i ignorert workspace.")
    folder=destination/(time.strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    print("Backup 1/2: Leser hele flashen. Ingen skriving til enheten.",flush=True)
    raw=transport.read(0,FLASH_SIZE)
    require(len(raw)==FLASH_SIZE, "Full backup kunne ikke leses. Ingen skriving er startet.")
    binary=folder/"flash.bin"
    with binary.open("xb") as handle:
        handle.write(raw);handle.flush();os.fsync(handle.fileno())
    require(binary.stat().st_size==FLASH_SIZE and sha(binary.read_bytes())==sha(raw), "Backup på disk stemmer ikke.")
    print("Backup 2/2: Leser flashen på nytt for å kontrollere kopien.",flush=True)
    compare=transport.read(0,FLASH_SIZE)
    require(len(compare)==FLASH_SIZE and sha(compare)==sha(raw), "Backup stemmer ikke med en ny full avlesning. Ingen skriving tillates.")
    try:rows=partition_rows(raw[0x8000:0x9000])
    except MigrationError:rows=[]
    layout="legacy-default-16mb" if rows==LEGACY else "fire-ab-recovery-v1" if rows==PARTITIONS else "unknown"
    metadata={"schema":1,"size":FLASH_SIZE,"sha256":sha(raw),"security":info,"created_at":int(time.time()),"layout":layout}
    with (folder/"backup.json").open("x",encoding="utf-8") as handle:
        json.dump(metadata,handle,indent=2);handle.flush();os.fsync(handle.fileno())
    print("Full backup er kontrollert og lagret: "+str(folder),flush=True)
    return folder,raw


def migrate(bundle,transport,backup_dir):
    info=transport.security();check_security(info,bundle)
    folder,original=backup(transport,backup_dir,info)
    try:rows=partition_rows(original[0x8000:0x9000])
    except MigrationError:rows=[]
    require(rows in (LEGACY,PARTITIONS), "Eksisterende layout er ukjent. Full backup beholdes; ingen migrering tillates.")
    # Safety information is re-read after the potentially long backup.
    current=transport.security();check_security(current,bundle)
    require(current==info,"Enhetens identitet eller sikkerhetsstatus endret seg. Ingen skriving tillates.")
    for role in ("normal","recovery","partitions","bootloader"):
        data=bundle.images[role];offset=ROLES[role][1]
        print("Skriver og kontrollerer "+ROLES[role][0]+" …",flush=True)
        transport.write(offset,data)
        require(transport.read(offset,len(data))==data,"Skriving kunne ikke bekreftes. Bruk den verifiserte backupen for gjenoppretting.")
    print("Klargjør oppstart av recovery …",flush=True)
    transport.erase_ota()
    require(transport.read(0xE000,0x2000)==b"\xff"*0x2000,"Valg av recovery kunne ikke bekreftes.")
    transport.reset()
    return folder


def restore(directory,transport,backup_dir):
    directory=Path(directory).resolve()
    metadata=strict_json(read_file(directory,"backup.json",8192))
    data=read_file(directory,"flash.bin",FLASH_SIZE)
    require(isinstance(metadata,dict) and set(metadata)=={"schema","size","sha256","security","created_at","layout"}
            and metadata["schema"]==1 and metadata["size"]==FLASH_SIZE and len(data)==FLASH_SIZE and metadata["sha256"]==sha(data), "Backupen er endret eller ufullstendig.")
    info=transport.security();check_security(info);check_security(metadata["security"])
    require(info["mac"]==metadata["security"]["mac"] and info["flash_id"]==metadata["security"]["flash_id"], "Backupen tilhører en annen fysisk enhet.")
    require(partition_rows(data[0x8000:0x9000]) in (LEGACY,PARTITIONS), "Backupen har ukjent layout.")
    folder,_=backup(transport,backup_dir,info)
    require(transport.security()==info,"Enheten endret seg etter backup.")
    print("Gjenoppretter den verifiserte kopien …",flush=True)
    transport.write(0,data)
    require(transport.read(0,FLASH_SIZE)==data,"Gjenopprettingen kunne ikke bekreftes. Ikke koble fra før feilen er undersøkt.")
    transport.reset()
    return folder


def main(argv=None):
    parser=argparse.ArgumentParser(description="Sikker FIRE-migrering. Ingen skriving i standardmodus.")
    parser.add_argument("command",nargs="?",default="check",choices=("check","ports","preflight","migrate","restore"))
    parser.add_argument("--bundle",type=Path)
    parser.add_argument("--port")
    parser.add_argument("--backup-dir",type=Path,default=BACKUPS)
    parser.add_argument("--backup",type=Path)
    parser.add_argument("--baud",type=int,choices=(115200,460800,921600),default=921600)
    parser.add_argument("--confirm",choices=("MIGRATE-FIRE","RESTORE-FIRE"))
    args=parser.parse_args(argv)
    transport=None
    try:
        if args.command=="ports":
            try:
                from serial.tools.list_ports import comports
            except ImportError: raise MigrationError("Installer requirements-migration.txt for å vise serieporter.") from None
            for port in comports(): print(port.device+" · "+port.description)
            return 0
        if args.command=="restore":
            require(args.confirm=="RESTORE-FIRE" and args.backup is not None,"Gjenoppretting krever --backup og --confirm RESTORE-FIRE.")
            require(args.port is not None,"Velg serieport med --port COM3.")
            transport=EsptoolTransport(args.port,args.baud)
            folder=restore(args.backup,transport,args.backup_dir)
            print("Gjenoppretting er skrevet og kontrollert. Ny backup: "+str(folder));return 0
        require(args.bundle is not None,"Oppgi --bundle med en ferdig, signert migrasjonspakke. Ingen enhet er kontaktet.")
        bundle=validate_bundle(args.bundle)
        if args.command=="check":
            print("Pakken er signatur-, hash-, bilde- og layoutkontrollert. Ingen serieport er åpnet; ingenting er skrevet.");return 0
        require(args.port is not None,"Velg serieport med --port COM3.")
        if args.command=="migrate":require(args.confirm=="MIGRATE-FIRE","Migrering krever --confirm MIGRATE-FIRE. Ingenting er skrevet.")
        transport=EsptoolTransport(args.port,args.baud)
        if args.command=="preflight":
            check_security(transport.security(),bundle);transport.reset()
            print("ESP32, 16 MiB og sikkerhetsstatus er kontrollert. Ingen flashskriving.");return 0
        folder=migrate(bundle,transport,args.backup_dir)
        print("Bildene er skrevet og kontrollert. Kontroller recovery på FIRE-skjermen. Backup: "+str(folder))
        return 0
    except (MigrationError,OSError,ValueError,TypeError,KeyError) as error:
        print("STOPPET: "+str(error),file=sys.stderr)
        return 2
    except Exception:
        print("STOPPET: Serietilkobling eller enhetskontroll feilet. Ingen automatisk gjentakelse. Behold backupen.",file=sys.stderr)
        return 2
    finally:
        if transport:
            try:transport.close()
            except Exception:pass


if __name__=="__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
