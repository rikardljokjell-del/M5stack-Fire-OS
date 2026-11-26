"""Portable UART policy; Windows compiles only, Linux executes the real C++."""
import os
import importlib.util
import sys
from unittest import mock
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_native_guards as native

SCRIPT=native.ROOT.parent/'M5Stack-backend/scripts/local_qa.py'
spec=importlib.util.spec_from_file_location('fire_local_qa_host_test',SCRIPT)
host=importlib.util.module_from_spec(spec);sys.modules[spec.name]=host;spec.loader.exec_module(host)
KEY=b'fire-local-qa-golden-key-2026'
NONCE='0123456789abcdef0123456789abcdef'
IDENTITY='a'*64


def response(auth,seq=0,*,code=0,duplicate=0,presented=1,label='Main',detail='Ready'):
    values=['FQ1','R',NONCE,str(seq),str(code),str(duplicate),'490','2','1','4','7',
            '0000000000000009',IDENTITY,str(presented),'0','0','12345678',
            label.encode().hex(),detail.encode().hex()]
    return auth.encode('|'.join(values))


class FakeSerial:
    """Wire/auth codec exercise only; no hardware, provider, Vault or sockets."""
    def __init__(self):
        self.auth=host.Authenticator(KEY);self.rx=bytearray();self.writes=[]
        self.actions=0;self.presented=1;self.closed=False;self.drop=0;self.last=b'';self.reply=b''
    def write(self,wire):
        self.writes.append(wire)
        if wire==b'FQ1|HELLO\n':
            answer=self.auth.encode('FQ1|C|'+NONCE+'|110000')
        else:
            fields=self.auth.decode(wire)
            if fields[1]=='ARM':answer=response(self.auth)
            elif wire==self.last:answer=self.reply
            else:
                assert fields[1]=='DO'
                if fields[4] in {'CLICK','HOLD'}:
                    assert fields[6:9]==['7','0000000000000009',IDENTITY]
                    self.actions+=1;self.presented+=1
                answer=response(self.auth,int(fields[3]),presented=self.presented)
                self.last,self.reply=wire,answer
        if self.drop:self.drop-=1
        else:self.rx.extend(answer)
        return len(wire)
    def read(self,size):
        result=bytes(self.rx[:size]);del self.rx[:size];return result
    def close(self):self.closed=True


class LocalQaHostTests(unittest.TestCase):
    def test_exact_domain_hmac_golden(self):
        auth=host.Authenticator(KEY)
        body='FQ1|ARM|'+NONCE+'|300|500|3'
        wire=auth.encode(body)
        self.assertEqual(wire.rsplit(b'|',1)[1].strip(),
            b'2181094617012cd71a070c4812eb74bdb8463c4205fc6514e7d51bd342f2708a')
        self.assertEqual(auth.decode(wire),body.split('|'))
        changed=wire[:-2]+(b'0' if wire[-2:-1]!=b'0' else b'1')+b'\n'
        with self.assertRaises(host.QaError):auth.decode(changed)
        with self.assertRaises(host.QaError):auth.encode('x'*500)
        with self.assertRaises(host.QaError):auth.decode(wire.replace(b'FQ1',b'F\r1'))

    def test_strict_response_binding_utf8_and_bounds(self):
        auth=host.Authenticator(KEY)
        parts=auth.decode(response(auth,3,label='Måledata'))
        snapshot=host.decode_snapshot(parts,NONCE,3)
        self.assertEqual(snapshot.label,'Måledata')
        for nonce,seq in [('f'*32,3),(NONCE,2)]:
            with self.assertRaises(host.QaError):host.decode_snapshot(parts,nonce,seq)
        for field,value in [(3,'03'),(5,'2'),(7,'65536'),(17,'ff'),(18,'61'*33)]:
            bad=parts[:];bad[field]=value
            with self.assertRaises(host.QaError):host.decode_snapshot(bad,NONCE,3)

    def test_button_is_bound_to_cached_presented_scope_and_exact_retry(self):
        stream=FakeSerial()
        session=host.Session(stream,KEY,buttons=True,safe_package=host.SAFE_PACKAGE,
            safe_source=host.SAFE_SOURCE,timeout=.01)
        initial=session.arm();stream.drop=1
        final=session.button('B',expected=initial)
        self.assertEqual(stream.actions,1)
        self.assertGreater(final.presented,initial.presented)
        self.assertEqual(stream.writes[2],stream.writes[3])
        self.assertEqual(session.public(final)['label'],'Main')
        session.close();self.assertTrue(stream.closed)
        self.assertEqual(session.auth._key,bytearray(len(KEY)))

    def test_unknown_action_never_reissued_as_fresh_sequence(self):
        stream=FakeSerial()
        session=host.Session(stream,KEY,buttons=True,safe_package=host.SAFE_PACKAGE,
            safe_source=host.SAFE_SOURCE,timeout=.01)
        initial=session.arm();stream.drop=2
        with self.assertRaises(host.QaError):session.button('B',expected=initial)
        writes=len(stream.writes)
        with self.assertRaises(host.QaError):session.button('B',expected=initial)
        self.assertEqual(len(stream.writes),writes)
        self.assertEqual(stream.actions,1)
        session.close();self.assertTrue(stream.closed)

    def test_state_only_and_fixture_allowlist(self):
        stream=FakeSerial();session=host.Session(stream,KEY)
        state=session.arm()
        with self.assertRaises(host.QaError):session.button('A',expected=state)
        self.assertEqual(stream.actions,0);session.close()
        with self.assertRaises(host.QaError):host.require_safe_app('other',host.SAFE_SOURCE)
        with self.assertRaises(host.QaError):host.Session(FakeSerial(),KEY,buttons=True)

    def test_plan_preflight_and_import_never_open_com_or_vault(self):
        good=[{'op':'state'},{'op':'select','label':'AI Developer','screen':2},
              {'op':'button','button':'B','expect':{'label':'Build'}},
              {'op':'wait','expect':{'busy':False},'timeout':20}]
        self.assertEqual(host.validate_plan(good),good)
        for bad in [[{'op':'eval'}],[{'op':'state','url':'https://invalid'}],
                    [{'op':'button','button':'B','hold':'false'}],
                    [{'op':'wait','timeout':float('nan')}]]:
            with self.assertRaises(host.QaError):host.validate_plan(bad)
        with mock.patch.object(host,'device_key') as vault, mock.patch.object(host,'open_port') as port:
            with tempfile.TemporaryDirectory() as folder:
                plan=Path(folder)/'invalid.json';plan.write_text('[{"op":"eval"}]')
                self.assertEqual(host.main(['--port','COM3','--safe-package',host.SAFE_PACKAGE,
                    '--safe-source',host.SAFE_SOURCE,'batch',str(plan)]),1)
            vault.assert_not_called();port.assert_not_called()


class LocalQaPolicyTests(unittest.TestCase):
    def test_strict_cpp11_policy_compiles(self):
        compiler=native.host_compiler()
        if compiler is None:self.skipTest('No C++ host compiler')
        if Path(compiler).stem.lower() in ('cl','clang-cl'):
            self.skipTest('Compiler has no strict C++11 mode')
        prefix=[compiler,'c++'] if Path(compiler).stem.lower()=='zig' else [compiler]
        if Path(compiler).stem.lower()=='zig' and os.name=='nt':prefix+=['-target','x86_64-windows-gnu']
        with tempfile.TemporaryDirectory(prefix='fire-local-qa-') as folder:
            command=prefix+['-std=c++11','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(native.ROOT/'src'),'-c',str(native.ROOT/'tests/native_local_qa.cpp'),'-o',str(Path(folder)/'policy.o')]
            result=subprocess.run(command,capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipIf(os.name=='nt','Windows App Control: compilation only here; execution belongs to Linux CI')
    def test_actual_policy(self):
        output=native.NativeGuardTests().run_native('native_local_qa.cpp')
        self.assertIn('PASS authenticated local QA policy',output)


if __name__=='__main__':unittest.main()
