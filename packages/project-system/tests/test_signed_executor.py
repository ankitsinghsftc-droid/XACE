"""Signed build identity tests; synthetic PE/certificate bytes are never executed."""
import copy,hashlib,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_executor_contract as contract
import signed_executor as signed
import pe_derivation as pe
from test_native_executor_contract import fixture

def pe_pair():
    raw=bytearray(1021);raw[:2]=b'MZ';struct.pack_into('<I',raw,0x3c,128);raw[128:132]=b'PE\0\0';struct.pack_into('<H',raw,132,0x8664);struct.pack_into('<H',raw,148,240);struct.pack_into('<H',raw,152,0x20b);struct.pack_into('<I',raw,260,16);struct.pack_into('<I',raw,216,12345)
    original=bytes(raw);raw.extend(b'\0'*3);raw.extend(struct.pack('<IHH',24,0x200,2)+b'FAKE NEVER TRUST');struct.pack_into('<II',raw,296,1024,24);struct.pack_into('<I',raw,216,54321)
    return original,bytes(raw)

def signed_fixture():
    r,_,package=fixture();before,after=pe_pair();h=contract.sha(before);r['executable_sha256']=h;r['shipping']['required_files']['runtime/xace_runtime.exe']=h
    for output in r['build']['independent_outputs']:output['executable_sha256']=h
    outer=copy.deepcopy(r);outer.update(schema=signed.SCHEMA,executable_sha256=contract.sha(after),derivation=dict(schema=signed.DERIVATION,unsigned_receipt=copy.deepcopy(r),unsigned_receipt_sha256=contract.digest(r),signer_certificate_sha256='a'*64,trust_policy=signed.POLICY,unsigned_length=len(before),unsigned_pe_checksum=12345));outer['shipping']['required_files']['runtime/xace_runtime.exe']=outer['executable_sha256']
    return outer,before,after,package

def policy():return dict(schema='xace.publisher_policy.v1',trust_policy=signed.POLICY,allowed_signer_certificate_sha256=['a'*64])

class SignedExecutorTests(unittest.TestCase):
    def test_signed_contract_retains_both_unsigned_build_hashes(self):
        r,before,after,_=signed_fixture();self.assertEqual(contract.validate(r),r)
        self.assertTrue(all(o['executable_sha256']==contract.sha(before) for o in r['build']['independent_outputs']))
        self.assertNotEqual(contract.sha(before),contract.sha(after))
    def test_signing_cannot_change_authority_or_reproduction(self):
        r,*_=signed_fixture()
        for change in [lambda v:v['capabilities'].append('forged.v1'),lambda v:v['systems'][0].update(deterministic=False),lambda v:v['source_files'].update({'new.rs':'f'*64}),lambda v:v['build']['independent_outputs'][0].update(executable_sha256=v['executable_sha256']),lambda v:v['compatibility'].update(snapshot_schema='forged.v1'),lambda v:v.update(extra=True)]:
            v=copy.deepcopy(r);change(v)
            with self.assertRaises(ValueError):contract.validate(v)
    def test_original_receipt_must_be_valid_and_pinned(self):
        r,*_=signed_fixture()
        for change in [lambda d:d.update(unsigned_receipt_sha256='0'*64),lambda d:d['unsigned_receipt'].update(schema=signed.SCHEMA),lambda d:d.update(unsigned_length=True),lambda d:d.update(unsigned_pe_checksum=-1),lambda d:d.update(trust_policy='allow_any')]:
            v=copy.deepcopy(r);change(v['derivation'])
            with self.assertRaises(ValueError):contract.validate(v)
    def test_unsigned_schema_cannot_hide_signed_derivation(self):
        r,*_=signed_fixture();r['schema']=contract.SCHEMA
        with self.assertRaises(ValueError):contract.validate(r)
    def test_strict_machine_code_preservation_and_padding(self):
        r,_,after,_=signed_fixture();d=r['derivation'];args=dict(unsigned_sha256=d['unsigned_receipt']['executable_sha256'],unsigned_length=d['unsigned_length'],unsigned_pe_checksum=d['unsigned_pe_checksum']);pe.verify(after,**args)
        for offset in [0,128,132,260,500,1022,1028]:
            changed=bytearray(after);changed[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(ValueError):pe.verify(bytes(changed),**args)
        with self.assertRaises(ValueError):pe.verify(after+b'overlay',**args)
    def test_unrelated_signed_pe_cannot_claim_original_build(self):
        r,_,after,_=signed_fixture();changed=bytearray(after);changed[700]=99
        with self.assertRaisesRegex(ValueError,'reproduced'):pe.verify(bytes(changed),unsigned_sha256=r['derivation']['unsigned_receipt']['executable_sha256'],unsigned_length=1021,unsigned_pe_checksum=12345)
    def test_no_timestamp_or_publisher_claim_bypasses_windows(self):
        r,_,after,package=signed_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'signed.exe';exe.write_bytes(after)
            args=dict(expected_receipt_digest=contract.digest(r),executable=exe,required_capabilities=r['capabilities'],expected_compatibility=r['compatibility'],package=package)
            with self.assertRaisesRegex(ValueError,'publisher policy'):contract.admit(r,**args)
            bad=policy();bad['allowed_signer_certificate_sha256']=['b'*64]
            with patch('windows_authenticode.verify') as verifier:
                with self.assertRaisesRegex(ValueError,'not approved'):contract.admit(r,publisher_policy=bad,**args)
                verifier.assert_not_called()
            # Actual OS refusal of this synthetic non-signature, never a mocked PASS.
            with self.assertRaisesRegex(ValueError,'Authenticode|Windows'):contract.admit(r,publisher_policy=policy(),**args)
    def test_host_pinned_policy_is_immutable_and_rechecked(self):
        r,_,after,package=signed_fixture();r['capabilities']=sorted(set(r['capabilities']+['native.structured_transform.v1']))
        # Mutating outer capabilities is prohibited; update the original reviewed
        # fixture equally and refresh its independently reviewed receipt digest.
        r['derivation']['unsigned_receipt']['capabilities']=r['capabilities'][:];r['derivation']['unsigned_receipt_sha256']=contract.digest(r['derivation']['unsigned_receipt'])
        p=policy()
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'signed.exe';exe.write_bytes(after)
            host=contract.TrustedExecutor(r,expected_receipt_digest=contract.digest(r),executable=exe,expected_compatibility=r['compatibility'],publisher_policy=p)
            p['allowed_signer_certificate_sha256'].clear()
            with patch('windows_authenticode.verify',return_value={'test_only':True}) as verifier:
                host.require_structured_transform(package);self.assertEqual(verifier.call_args.args[1],'a'*64)
            exe.write_bytes(after+b'changed')
            with self.assertRaisesRegex(ValueError,'Executable changed'):host.require_structured_transform(package)
    def test_creator_derivation_requires_exact_unsigned_and_windows_trust(self):
        r,before,after,_=signed_fixture();original=r['derivation']['unsigned_receipt']
        with tempfile.TemporaryDirectory() as tmp:
            u=Path(tmp)/'unsigned.exe';u.write_bytes(before);s=Path(tmp)/'signed.exe';s.write_bytes(after)
            args=dict(expected_unsigned_digest=contract.digest(original),unsigned_executable=u,signed_executable=s,policy=policy())
            with patch('windows_authenticode.inspect',return_value=dict(executable_sha256=contract.sha(after),signer_certificate_sha256='a'*64)):
                self.assertEqual(signed.derive(original,**args),r)
                with self.assertRaisesRegex(ValueError,'pinned'):signed.derive(original,**{**args,'expected_unsigned_digest':'0'*64})
                altered=bytearray(after);altered[600]^=1;s.write_bytes(altered)
                with self.assertRaisesRegex(ValueError,'reproduced'):signed.derive(original,**args)
    def test_policy_has_no_disable_or_empty_allowlist(self):
        for value in [None,{},dict(policy(),allowed_signer_certificate_sha256=[]),dict(policy(),trust_policy='skip'),dict(policy(),extra=True),dict(policy(),allowed_signer_certificate_sha256=['a'*64,'a'*64])]:
            with self.assertRaises(ValueError):signed.publisher_policy(value)
if __name__=='__main__':unittest.main()
