"""Single known experimental hash decoder cannot authorize live delivery."""
import copy
import hashlib
from pathlib import Path
import zipfile

import pytest

from fire_backend.app_sdk import SDK_VERSION,SDK_CONTRACT
from fire_backend.builds import write_archive,verify_archive
from fire_backend.models import Manifest
from scripts.revalidate_sdk_history import read_historical_source,EXPERIMENTAL_HASH


def artifact(tmp_path,**changes):
    payload=b'function init() end\r\nfunction update(dt) fire.display.pixel(0,0,31) end'
    manifest=Manifest(id='sdk-old',name='Old experiment',version='0.1.1',api_version=SDK_VERSION,
        api_contract=SDK_CONTRACT,required_services=['display'],permissions=['fire.display'],
        checksum=hashlib.sha256(payload).hexdigest()).model_dump()
    manifest.update(api_contract=EXPERIMENTAL_HASH,**changes)
    path=tmp_path/'old.zip';write_archive(path,manifest,payload)
    return path,manifest,payload


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def test_historical_source_is_raw_byte_preserved_and_still_rejected_live(tmp_path):
    path,manifest,payload=artifact(tmp_path);before=path.read_bytes();metadata=copy.deepcopy(manifest)
    assert read_historical_source(path,manifest,digest(path))==payload
    assert path.read_bytes()==before and manifest==metadata
    with pytest.raises(ValueError,match='SDK manifest contract mismatch'):verify_archive(path,manifest,digest(path))


def test_historical_decoder_rejects_wrong_hash_identity_layout_and_payload(tmp_path):
    path,manifest,payload=artifact(tmp_path)
    with pytest.raises(ValueError,match='ZIP checksum'):read_historical_source(path,manifest,'0'*64)
    with pytest.raises(ValueError,match='known unpublished'):read_historical_source(path,{**manifest,'api_contract':'0'*64},digest(path))
    with pytest.raises(ValueError,match='manifest mismatch'):read_historical_source(path,{**manifest,'name':'Changed'},digest(path))
    with zipfile.ZipFile(path,'a') as archive:archive.writestr('extra.txt','unexpected')
    with pytest.raises(ValueError,match='layout'):read_historical_source(path,manifest,digest(path))


def test_historical_decoder_checks_crc_even_if_outer_digest_is_recomputed(tmp_path):
    path,manifest,payload=artifact(tmp_path);data=bytearray(path.read_bytes());at=data.index(payload);data[at]^=1;path.write_bytes(data)
    with pytest.raises(ValueError,match='CRC'):read_historical_source(path,manifest,digest(path))


def test_historical_decoder_checks_source_checksum_and_strict_structure(tmp_path):
    path,manifest,payload=artifact(tmp_path,checksum='0'*64)
    with pytest.raises(ValueError,match='source checksum'):read_historical_source(path,manifest,digest(path))
    path,manifest,payload=artifact(tmp_path,unexpected=True)
    with pytest.raises(ValueError):read_historical_source(path,manifest,digest(path))
