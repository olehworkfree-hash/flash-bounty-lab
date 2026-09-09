import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import bounded_screen as b
from rpc_transport import SafeTransportError


class BoundedScreenTest(unittest.TestCase):
    def command(self, root, label, *, mode='ok', delay=0, token='case', value=7):
        target = root/label/'result.json'
        program = (
            'import json,os,time;from pathlib import Path;'
            f"p=Path({str(target)!r});p.parent.joinpath('pid').write_text(str(os.getpid()));"
            f"p.parent.joinpath('checkpoint.json').write_text('{{\"status\":\"PARTIAL\"}}');time.sleep({delay!r});"
        )
        if mode == 'crash':
            program += 'raise SystemExit(9)'
        elif mode == 'malformed':
            program += "p.write_text('[')"
        elif mode == 'oversize':
            program += f"p.write_text(' '*{b.MAX_DOCUMENT+1})"
        else:
            doc = dict(status='PASS', provider=label, token=token, observation=dict(output=value))
            program += f'p.write_text({json.dumps(doc)!r})'
        # Isolated stdlib-only child: site customization is not part of this test.
        return [sys.executable, '-I', '-S', '-c', program]

    def run_case(self, root, modes, timeout=2):
        commands = {name:self.command(root,name,**kw) for name,kw in modes.items()}
        return b.run_workers(commands,root,'case',timeout=timeout)

    def test_fast_readers_complete(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.run_case(Path(d),{'a':{},'b':{}})
            self.assertTrue(r['all_children_reaped'])
            self.assertEqual([x['status'] for x in r['workers'].values()],['PASS','PASS'])

    def test_hanging_reader_stops_and_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);start=time.monotonic()
            r=self.run_case(root,{'a':{},'b':{},'slow':{'delay':30}},timeout=2.0)
            self.assertLess(time.monotonic()-start,5)
            self.assertEqual(r['workers']['slow']['status'],'DEADLINE')
            self.assertEqual(r['workers']['a']['status'],'PASS')
            self.assertTrue((root/'slow/checkpoint.json').exists())
            self.assertTrue(r['all_children_reaped'])
            pid=int((root/'slow/pid').read_text())
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)

    def test_crash_is_not_a_vote(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.run_case(Path(d),{'a':{},'b':{'mode':'crash'}})
            self.assertEqual(r['workers']['b']['returncode'],9)
            self.assertEqual(r['workers']['b']['status'],'FAILED')

    def test_stale_identity_is_not_a_vote(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.run_case(Path(d),{'a':{},'b':{'token':'stale'}})
            self.assertEqual(r['workers']['b']['status'],'FAILED')

    def test_bad_document_is_not_a_vote(self):
        for mode in ['malformed','oversize']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                r=self.run_case(Path(d),{'a':{},'b':{'mode':mode}})
                self.assertEqual(r['workers']['b']['status'],'FAILED')

    def test_old_output_directory_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'a').mkdir()
            with self.assertRaises(FileExistsError):self.run_case(root,{'a':{},'b':{}})

    def test_limits_checked_before_process_creation(self):
        for count,seconds in [(1,1),(5,1),(2,0),(2,121)]:
            with tempfile.TemporaryDirectory() as d,self.assertRaises(ValueError):
                self.run_case(Path(d),{str(i):{} for i in range(count)},timeout=seconds)

    def test_unsafe_label_rejected(self):
        with tempfile.TemporaryDirectory() as d,self.assertRaises(ValueError):
            b.run_workers({'../x':[],'a':[]},Path(d),'x')

    def test_single_reader_never_quorum(self):
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_COMPLETE_PROVIDERS'):
            b.strict_agreement({'a':{'out':1}})

    def test_dissent_not_hidden_by_majority(self):
        with self.assertRaisesRegex(ValueError,'COMPLETE_PROVIDER_CONFLICT'):
            b.strict_agreement({'a':{'out':1},'b':{'out':1},'c':{'out':2}})

    def test_matching_full_captures(self):
        value,voters=b.strict_agreement({'b':{'out':1},'a':{'out':1}})
        self.assertEqual(value,{'out':1});self.assertEqual(voters,['a','b'])

    def test_safe_error_never_exports_server_text(self):
        for exc in [RuntimeError('https://secret'),ValueError('https://secret'),KeyError('password')]:
            self.assertEqual(b.safe_code(exc),'CAPTURE_FAILED')
        self.assertEqual(b.safe_code(SafeTransportError('RPC_TRANSPORT_EXHAUSTED')),'RPC_TRANSPORT_EXHAUSTED')

    def test_atomic_replace_complete_json(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'nested/record.json'
            b.atomic_json(p,{'a':1});b.atomic_json(p,{'a':2})
            self.assertEqual(json.loads(p.read_text()),{'a':2})
            self.assertEqual(len(list(p.parent.iterdir())),1)

    def test_journal_keeps_each_successful_batch(self):
        def fake(req,limit):
            calls=json.loads(req.data)
            return json.dumps([dict(jsonrpc='2.0',id=c['id'],result='0x00') for c in calls]).encode()
        with tempfile.TemporaryDirectory() as d,patch.object(b.v,'fetch_body',side_effect=fake),patch.object(b.v.time,'sleep'):
            reader=b.JournalReader('arbitrum-official',{},directory=d)
            result=reader.read([reader.code(b.v.WETH)]*13)
            self.assertEqual(len(result),13);self.assertEqual(reader.count,13)
            records=[json.loads(p.read_text()) for p in sorted(Path(d).glob('batch-*.json'))]
            self.assertEqual([x['count'] for x in records],[12,1])
            self.assertTrue(all(x['status']=='COMPLETE' for x in records))

    def test_failed_batch_remains_diagnostic(self):
        with tempfile.TemporaryDirectory() as d,patch.object(b.v,'fetch_body',side_effect=TimeoutError('secret url')):
            reader=b.JournalReader('arbitrum-official',{},directory=d)
            with self.assertRaises(TimeoutError):reader.read([reader.code(b.v.WETH)])
            text=(Path(d)/'progress.json').read_text()
            self.assertEqual(json.loads(text)['status'],'FAILED');self.assertNotIn('secret',text)

    def test_read_only_and_call_limit_survive_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            reader=b.JournalReader('arbitrum-official',{},directory=d)
            with self.assertRaisesRegex(ValueError,'READ_ONLY_POLICY'):reader.read([('eth_sendRawTransaction',[])])
            with self.assertRaisesRegex(ValueError,'CALL_BUDGET'):reader.read([reader.code(b.v.WETH)]*(b.v.MAX_CALLS+1))
            self.assertEqual(list(Path(d).iterdir()),[])

if __name__=='__main__':unittest.main()
