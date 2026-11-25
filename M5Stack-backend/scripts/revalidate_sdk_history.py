"""OFFLINE verification helpers for known, unpublished e697 SDK experiments.

Never imported by live delivery/Manifest validation. Original ZIPs, requests,
reviews and PNGs are immutable. No cohort runner, import, migration, package
creation, AI review or physical installation is provided by these helpers.
"""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from fire_backend.app_sdk import SDK_VERSION,SDK_CONTRACT
from fire_backend.models import Manifest
from fire_backend.storage import identifier


EXPERIMENTAL_HASH='e6972ef535053a898babec4b532be7418941d6adc00c5fd477828bb0b9940e57'


def read_historical_source(path,expected_manifest,archive_sha256):
    """Explicit single-hash historical decoder, NOT a live package acceptance."""
    path=Path(path)
    if path.stat().st_size>200000:raise ValueError('Historical archive exceeds bound')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=archive_sha256:raise ValueError('Historical ZIP checksum mismatch')
    if expected_manifest.get('api_version')!=SDK_VERSION or expected_manifest.get('api_contract')!=EXPERIMENTAL_HASH:
        raise ValueError('Only the known unpublished experimental SDK hash is allowed here')
    prefix='apps/'+identifier(expected_manifest['id'])+'/'
    expected={prefix+n for n in ('manifest.json','main.lua','assets/','appdata/')}
    with zipfile.ZipFile(BytesIO(data)) as archive:
        if len(archive.infolist())!=4 or set(archive.namelist())!=expected:raise ValueError('Historical ZIP layout mismatch')
        for info in archive.infolist():
            limit=100000 if info.filename==prefix+'main.lua' else 8192 if info.filename==prefix+'manifest.json' else 0
            if info.file_size>limit:raise ValueError('Historical ZIP member exceeds bound')
        if archive.testzip() is not None:raise ValueError('Historical ZIP CRC mismatch')
        manifest=json.loads(archive.read(prefix+'manifest.json').decode('utf-8'))
        if manifest!=expected_manifest:raise ValueError('Historical manifest mismatch')
        # Current structural validation on a COPY does not authorize the old
        # hash in Manifest, endpoints or the actual immutable archive.
        normalized=Manifest.model_validate({**manifest,'api_contract':SDK_CONTRACT}).model_dump()
        normalized['api_contract']=EXPERIMENTAL_HASH
        if normalized!=manifest:raise ValueError('Historical manifest structure mismatch')
        source=archive.read(prefix+'main.lua')
    if hashlib.sha256(source).hexdigest()!=manifest['checksum']:raise ValueError('Historical source checksum mismatch')
    source.decode('utf-8')
    return source


def pixel_hashes(evidence,folder,source_sha256):
    if evidence.get('source_sha256')!=source_sha256:raise ValueError('Historical visual source mismatch')
    hashes=[]
    for frame in evidence.get('frames',[]):
        digest=frame['png_sha256']
        if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('Invalid historical PNG identity')
        path=folder/(digest[:24]+'.png')
        if path.stat().st_size>240000:raise ValueError('Historical PNG exceeds bound')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Historical PNG checksum mismatch')
        with Image.open(BytesIO(data)) as image:
            if image.size!=(320,240):raise ValueError('Historical PNG dimensions mismatch')
            actual=hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
        if actual!=frame['pixel_sha256']:raise ValueError('Historical pixel checksum mismatch')
        hashes.append(actual)
    return hashes
