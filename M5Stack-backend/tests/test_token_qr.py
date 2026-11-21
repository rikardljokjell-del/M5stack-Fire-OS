import pytest
from pydantic import SecretStr

from fire_backend.token_qr import token_matrix
from test_device_protocol import configured, TOKEN


def test_qr_encodes_only_the_selected_device_token(tmp_path, monkeypatch):
    import qrcode
    received = []
    original = qrcode.QRCode.add_data
    def record(self, value, *args, **kwargs):
        received.append(value)
        return original(self, value, *args, **kwargs)
    monkeypatch.setattr(qrcode.QRCode, "add_data", record)
    matrix = token_matrix(configured(tmp_path), "fire-01")
    assert received == [TOKEN]
    assert len(matrix) == len(matrix[0]) and any(any(row) for row in matrix)
    assert all(not any(row) for row in matrix[:4] + matrix[-4:])
    assert list(tmp_path.rglob("*")) == []


def test_missing_device_or_api_key_as_token_is_rejected(tmp_path):
    settings = configured(tmp_path)
    with pytest.raises(ValueError):
        token_matrix(settings, "unknown")
    settings.openai_api_key = SecretStr(TOKEN)
    with pytest.raises(ValueError):
        token_matrix(settings, "fire-01")
