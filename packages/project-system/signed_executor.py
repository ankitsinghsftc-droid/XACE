"""Versioned unsigned-build to signed-byte derivation; no signing or trust-store writes."""
import copy
from pathlib import Path
from authoring_identity import require
from windows_authenticode import POLICY

SCHEMA='xace.native_executor_build.v2'
DERIVATION='xace.authenticode_derivation.v1'

def publisher_policy(value):
    from native_executor_contract import hash_value
    require(type(value) is dict and set(value)=={'schema','trust_policy','allowed_signer_certificate_sha256'},'Explicit publisher policy required')
    require(value['schema']=='xace.publisher_policy.v1' and value['trust_policy']==POLICY,'Unsupported publisher trust policy')
    allowed=value['allowed_signer_certificate_sha256']
    require(type(allowed) is list and allowed and all(type(v) is str for v in allowed) and allowed==sorted(set(allowed)),'Sorted approved publisher certificates required')
    for cert in allowed:hash_value(cert)
    return copy.deepcopy(value)

def validate(receipt):
    from native_executor_contract import validate as unsigned_validate,digest,hash_value
    require(type(receipt) is dict and receipt.get('schema')==SCHEMA,'Signed executor receipt required')
    d=receipt.get('derivation')
    require(type(d) is dict and set(d)=={'schema','unsigned_receipt','unsigned_receipt_sha256','signer_certificate_sha256','trust_policy','unsigned_length','unsigned_pe_checksum'},'Exact signing derivation required')
    require(d['schema']==DERIVATION and d['trust_policy']==POLICY,'Unsupported signing derivation')
    require(type(d['unsigned_receipt']) is dict and d['unsigned_receipt'].get('schema')=='xace.native_executor_build.v1','Original v1 unsigned receipt required')
    original=unsigned_validate(d['unsigned_receipt']);require(digest(original)==d['unsigned_receipt_sha256'],'Original unsigned receipt identity changed')
    require(type(d['unsigned_length']) is int and 256<=d['unsigned_length']<=128*1024*1024 and type(d['unsigned_pe_checksum']) is int and 0<=d['unsigned_pe_checksum']<=0xffffffff,'Unsigned PE layout identity required')
    hash_value(d['signer_certificate_sha256']);hash_value(receipt.get('executable_sha256'))
    require(receipt['executable_sha256']!=original['executable_sha256'],'Signing must retain distinct unsigned and signed identities')
    expected=copy.deepcopy(original);expected.update(schema=SCHEMA,executable_sha256=receipt['executable_sha256'],derivation=copy.deepcopy(d));expected['shipping']['required_files']['runtime/xace_runtime.exe']=receipt['executable_sha256']
    require(receipt==expected,'Signing cannot alter source/build/system/capability/compatibility contracts')
    return copy.deepcopy(receipt)

def verify(receipt,executable,policy):
    from windows_authenticode import verify as windows_verify
    r=validate(receipt);p=publisher_policy(policy);cert=r['derivation']['signer_certificate_sha256']
    require(cert in p['allowed_signer_certificate_sha256'],'Signed executor publisher is not approved by host')
    from pe_derivation import verify as verify_pe
    from native_executor_contract import sha
    raw=Path(executable).read_bytes();require(sha(raw)==r['executable_sha256'],'Signed executor bytes changed')
    d=r['derivation'];verify_pe(raw,unsigned_sha256=d['unsigned_receipt']['executable_sha256'],unsigned_length=d['unsigned_length'],unsigned_pe_checksum=d['unsigned_pe_checksum'])
    return windows_verify(executable,cert)

def derive(unsigned_receipt,*,expected_unsigned_digest,unsigned_executable,signed_executable,policy):
    from native_executor_contract import validate as unsigned_validate,digest,sha
    from windows_authenticode import inspect
    require(type(unsigned_receipt) is dict and unsigned_receipt.get('schema')=='xace.native_executor_build.v1','Original v1 receipt required')
    original=unsigned_validate(unsigned_receipt);require(digest(original)==expected_unsigned_digest,'Unsigned receipt differs from independently pinned identity')
    require(sha(Path(unsigned_executable).read_bytes())==original['executable_sha256'],'Original unsigned executable changed')
    from pe_derivation import unsigned_identity,verify as verify_pe
    length,checksum=unsigned_identity(Path(unsigned_executable).read_bytes())
    p=publisher_policy(policy);report=inspect(signed_executable)
    verify_pe(Path(signed_executable).read_bytes(),unsigned_sha256=original['executable_sha256'],unsigned_length=length,unsigned_pe_checksum=checksum)
    require(report['signer_certificate_sha256'] in p['allowed_signer_certificate_sha256'],'Signed executable publisher is not approved')
    r=copy.deepcopy(original);r.update(schema=SCHEMA,executable_sha256=report['executable_sha256'],derivation=dict(schema=DERIVATION,unsigned_receipt=original,unsigned_receipt_sha256=digest(original),signer_certificate_sha256=report['signer_certificate_sha256'],trust_policy=POLICY,unsigned_length=length,unsigned_pe_checksum=checksum));r['shipping']['required_files']['runtime/xace_runtime.exe']=r['executable_sha256']
    return validate(r)

# Launcher signing has a separately host-pinned unsigned build identity. It is
# not an executor and cannot inherit the executor's compiler/source claims.
def derive_launcher(unsigned_executable,signed_executable,*,expected_unsigned_sha256,policy):
    from native_executor_contract import sha,hash_value
    from pe_derivation import unsigned_identity,verify as verify_pe
    from windows_authenticode import inspect
    hash_value(expected_unsigned_sha256);before=Path(unsigned_executable).read_bytes()
    require(sha(before)==expected_unsigned_sha256,'Unsigned launcher differs from trusted build identity')
    length,checksum=unsigned_identity(before);p=publisher_policy(policy);report=inspect(signed_executable)
    require(report['signer_certificate_sha256'] in p['allowed_signer_certificate_sha256'],'Launcher publisher is not approved')
    verify_pe(Path(signed_executable).read_bytes(),unsigned_sha256=expected_unsigned_sha256,unsigned_length=length,unsigned_pe_checksum=checksum)
    return dict(schema='xace.signed_launcher.v1',unsigned_sha256=expected_unsigned_sha256,executable_sha256=report['executable_sha256'],unsigned_length=length,unsigned_pe_checksum=checksum,signer_certificate_sha256=report['signer_certificate_sha256'])
