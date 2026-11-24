import json

import pytest

from scripts import capture_fire_diagnostics as d

LINE=b'FIRE diag loop_us=21 gap_us=22 callback_us=23 heap=100 min_heap=90 largest=80 min_largest=70 stack=60 rgb_timeouts=0'


def test_exact_metric_line_and_only_known_integer_fields():
    assert d.parse_line(LINE)==dict(zip(d.FIELDS,[21,22,23,100,90,80,70,60,0]))
    assert d.parse_line(LINE+b'\r') is not None
    for line in (b' '+LINE,b'prefix '+LINE,LINE+b' token=SECRET',LINE.replace(b'heap=100',b'heap=-1'),
                 LINE.replace(b'loop_us=21',b'loop_us=4294967296'),LINE+b'\nSSID=private',b'FIRE diag token=secret',b'x'*1024):
        assert d.parse_line(line) is None


def test_bounded_chunk_filter_recovers_after_long_secret_or_partial_line():
    f=d.LineFilter()
    assert f.feed(b'sk-secret TOKEN='+b'x'*2000)==[]
    assert len(f.buffer)<=d.MAX_LINE
    assert f.feed(b'\n'+LINE[:20])==[]
    assert f.feed(LINE[20:]+b'\r\n')==[d.parse_line(LINE)]


def test_capture_saves_only_structured_metrics_never_raw_logs(tmp_path):
    class Stream:
        def __init__(self):self.parts=iter([b'SSID=EXAMPLE_NETWORK token=PRIVATE_API_KEY\n'+LINE+b'\n',b'other log\n'])
        def read(self,size):assert size==256;return next(self.parts,b'')
    tick=[0]
    def clock():tick[0]+=.1;return tick[0]
    folder,summary=d.capture(Stream(),10,tmp_path,clock)
    text=''.join(p.read_text() for p in folder.iterdir())
    assert all(secret not in text for secret in ('PRIVATE_API_KEY','SSID','EXAMPLE_NETWORK','other log','FIRE diag'))
    assert summary['samples']==1 and summary['raw_serial_logs_saved'] is False
    assert summary['maxima']['callback_us']==23
    assert summary['minima']['heap']==100
    record=json.loads((folder/'metrics.jsonl').read_text())
    assert set(record)=={'received_at','elapsed_seconds','metrics'}


def test_default_help_never_opens_serial(monkeypatch,capsys):
    monkeypatch.setattr(d,'open_serial',lambda *_:pytest.fail('Default opened a serial port'))
    assert d.main([])==0
    assert '--port' in capsys.readouterr().out
    with pytest.raises(SystemExit):d.main(['--seconds','601','--port','COM3'])


def test_serial_port_control_lines_are_set_before_open(monkeypatch):
    import sys
    from types import SimpleNamespace
    calls=[]
    class Serial:
        def __init__(self,**options):
            assert options['port'] is None and options['baudrate']==115200 and options['timeout']==.25
        def open(self):calls.append((self.dtr,self.rts,self.port))
    monkeypatch.setitem(sys.modules,'serial',SimpleNamespace(Serial=Serial))
    d.open_serial('COM3')
    assert calls==[(False,False,'COM3')]
    with pytest.raises(ValueError):d.open_serial('guess-a-device')
