"""Capture only the exact bounded FIRE metric line, never ordinary serial logs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

FIELDS=("loop_us","gap_us","callback_us","heap","min_heap","largest","min_largest","stack","rgb_timeouts")
MEMORY=("heap","min_heap","largest","min_largest","stack")
MAX_LINE=512
MAX_SAMPLES=1000
OUTPUT=Path(__file__).resolve().parents[1]/"workspace"/"diagnostics"
PATTERN=re.compile(rb"FIRE diag "+b" ".join(key.encode()+rb"=([0-9]{1,10})" for key in FIELDS))


def parse_line(line):
    """No prefix search, no free text, no optional key/value extensions."""
    if not isinstance(line,bytes) or len(line)>MAX_LINE:
        return None
    if line.endswith(b"\r"):line=line[:-1]
    match=PATTERN.fullmatch(line)
    if not match:return None
    values=[int(value) for value in match.groups()]
    if any(value>0xFFFFFFFF for value in values):return None
    return dict(zip(FIELDS,values))


class LineFilter:
    def __init__(self):self.buffer=bytearray();self.dropping=False
    def feed(self,chunk):
        rows=[]
        for byte in chunk:
            if byte==10:
                if not self.dropping:
                    row=parse_line(bytes(self.buffer))
                    if row is not None:rows.append(row)
                self.buffer.clear();self.dropping=False
            elif not self.dropping:
                if len(self.buffer)>=MAX_LINE:
                    self.buffer.clear();self.dropping=True
                else:self.buffer.append(byte)
        return rows


def capture(stream,seconds,output=OUTPUT,clock=time.monotonic):
    """The serial port supplies bounded reads with a 250ms timeout; no writes."""
    start=clock();count=0;maxima={};minima={};interrupted=False
    folder=Path(output)/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    lines=LineFilter()
    with (folder/'metrics.jsonl').open('x',encoding='utf-8') as handle:
        try:
            while clock()-start<seconds and count<MAX_SAMPLES:
                chunk=stream.read(256)
                if not chunk:continue
                for row in lines.feed(chunk):
                    if count>=MAX_SAMPLES:break
                    record={'received_at':datetime.now(timezone.utc).isoformat(),
                            'elapsed_seconds':round(clock()-start,3),'metrics':row}
                    handle.write(json.dumps(record,separators=(',',':'))+'\n');handle.flush()
                    count+=1
                    for key,value in row.items():maxima[key]=max(maxima.get(key,value),value)
                    for key in MEMORY:minima[key]=min(minima.get(key,row[key]),row[key])
                    print(f'Mottatt måling {count}.',flush=True)
        except KeyboardInterrupt:
            interrupted=True
        handle.flush();os.fsync(handle.fileno())
    summary={'schema':1,'samples':count,'duration_seconds':round(clock()-start,3),
             'maxima':maxima,'minima':minima,'interrupted':interrupted,
             'sample_limit_reached':count>=MAX_SAMPLES,'raw_serial_logs_saved':False}
    with (folder/'summary.json').open('x',encoding='utf-8') as handle:
        json.dump(summary,handle,indent=2);handle.flush();os.fsync(handle.fileno())
    return folder,summary


def duration(value):
    try:number=int(value)
    except (ValueError,TypeError):raise argparse.ArgumentTypeError('Bruk hele sekunder fra 10 til 600.') from None
    if not 10<=number<=600:raise argparse.ArgumentTypeError('Bruk 10–600 sekunder.')
    return number


def open_serial(port):
    if not re.fullmatch(r'COM[1-9][0-9]*',port or '',re.I) and not re.fullmatch(r'/dev/(ttyUSB|ttyACM)[0-9]+',port or ''):
        raise ValueError('Velg en konkret serieport, for eksempel COM3.')
    try:import serial
    except ImportError:raise ValueError('Installer requirements-migration.txt først.') from None
    # Set inactive control lines BEFORE opening; no boot/reset command is sent.
    stream=serial.Serial(port=None,baudrate=115200,timeout=.25,xonxoff=False,rtscts=False,dsrdtr=False)
    stream.dtr=False;stream.rts=False;stream.port=port
    stream.open()
    return stream


def main(argv=None):
    parser=argparse.ArgumentParser(description='Samle bare FIREs ytelsesmålinger. Ingen serieport åpnes uten --port.')
    parser.add_argument('--port',help='FIREs serieport, for eksempel COM3')
    parser.add_argument('--seconds',type=duration,default=120,help='Varighet 10–600 sekunder (standard 120)')
    args=parser.parse_args(argv)
    if not args.port:
        parser.print_help();return 0
    stream=None
    try:
        stream=open_serial(args.port)
        print(f'Samler målinger i opptil {args.seconds} sekunder. Bruk FIRE som normalt. Ctrl+C avslutter tidlig.',flush=True)
        folder,summary=capture(stream,args.seconds)
        print('Lagret målinger: '+str(folder))
        if not summary['samples']:print('Ingen FIRE-målinger mottatt. Vanlige serielogger er ikke lagret.')
        return 0
    except (OSError,ValueError):
        print('Kunne ikke åpne porten eller lagre målinger. Kontroller porten og lukk andre serieovervåkere.')
        return 2
    finally:
        if stream:
            try:stream.close()
            except Exception:pass


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
