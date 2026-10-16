import copy
import tempfile
import unittest
from pathlib import Path
from test_native_reconciliation import context,engine_edit
from test_authoring_apply import FixtureGateway
from native_adoption import encode
from native_materialization import NativeMaterializationHost

class Gateway(FixtureGateway):
    def capture(self):return (self.root/'native.json').read_bytes()

class HostTests(unittest.TestCase):
    def fixture(self,root,edit=True):
        ctx=context()
        if edit:engine_edit(ctx)
        (root/'game.cgs.json').write_bytes(encode(ctx['current_cgs']))
        (root/'native.json').write_bytes(ctx['native_inventory'])
        return NativeMaterializationHost(root,lambda:ctx,Gateway(root)),ctx
    def approve(self,host):
        review=host.review.open('operator')
        return host.review.approve('operator',review['token'],review['proposal_digest'])
    def test_explicit_apply_commits_verified_pair_and_consumes_review(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,ctx=self.fixture(root);approval=self.approve(host)
            result=host.apply('operator',approval,approval['proposal_digest'])
            self.assertEqual(result['state'],'committed')
            self.assertFalse(result['runtime_activation'])
            self.assertTrue((root/'.xace/authoring-baseline.native.json').exists())
            with self.assertRaises(ValueError):host.apply('operator',approval,approval['proposal_digest'])
    def test_noop_does_not_write_files_or_journal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,_=self.fixture(root,False);before={p.name:p.read_bytes() for p in root.iterdir()};approval=self.approve(host)
            self.assertEqual(host.apply('operator',approval,approval['proposal_digest'])['state'],'noop')
            self.assertEqual({p.name:p.read_bytes() for p in root.iterdir() if p.is_file()},before)
            self.assertFalse((root/'.xace/authoring-transactions').exists())
    def test_stale_and_foreign_approval_cannot_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,ctx=self.fixture(root);approval=self.approve(host);before=(root/'game.cgs.json').read_bytes()
            with self.assertRaises(ValueError):host.apply('other',approval,approval['proposal_digest'])
            engine_edit(ctx,value='9')
            with self.assertRaises(ValueError):host.apply('operator',approval,approval['proposal_digest'])
            self.assertEqual((root/'game.cgs.json').read_bytes(),before)
    def test_incomplete_journal_blocks_apply(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,_=self.fixture(root);approval=self.approve(host)
            (root/'.xace/authoring-transactions/incomplete').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,'recovery blocks'):host.apply('operator',approval,approval['proposal_digest'])

if __name__=='__main__':unittest.main()
