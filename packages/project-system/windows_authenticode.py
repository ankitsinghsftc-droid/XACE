"""Read-only Windows Authenticode chain, signer DER and timestamp verification.

No key/store writes, shell, UI, target execution or fresh network retrieval.
"""
import ctypes as c
import hashlib,os
from pathlib import Path
from authoring_identity import require

POLICY='windows_authenticode_cached_chain.v1'

def inspect(path):
    require(os.name=='nt' and c.sizeof(c.c_void_p)==8,'Windows x64 Authenticode verification required')
    path=Path(path).resolve(strict=True)
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    u32=c.c_uint32;ptr=c.c_void_p
    class Guid(c.Structure):_fields_=[('a',u32),('b',c.c_uint16),('d',c.c_uint16),('tail',c.c_ubyte*8)]
    class File(c.Structure):_fields_=[('size',u32),('path',c.c_wchar_p),('handle',ptr),('subject',ptr)]
    class Trust(c.Structure):_fields_=[('size',u32),('policy',ptr),('sip',ptr),('ui',u32),('revocation',u32),('choice',u32),('file',c.POINTER(File)),('action',u32),('state',ptr),('url',c.c_wchar_p),('flags',u32),('context',u32),('settings',ptr)]
    class Cert(c.Structure):_fields_=[('encoding',u32),('encoded',c.POINTER(c.c_ubyte)),('length',u32),('info',ptr),('store',ptr)]
    class ProviderCert(c.Structure):_fields_=[('size',u32),('cert',c.POINTER(Cert))]
    class Signer(c.Structure):_fields_=[('size',u32),('time',u32*2),('count',u32),('chain',c.POINTER(ProviderCert)),('kind',u32),('info',ptr),('error',u32),('counter_count',u32),('counters',ptr),('context',ptr)]
    # LOAD_LIBRARY_SEARCH_SYSTEM32: project-local DLLs cannot supply trust APIs.
    dll=c.WinDLL('wintrust.dll',winmode=0x800)
    verify=dll.WinVerifyTrust;verify.argtypes=[ptr,c.POINTER(Guid),c.POINTER(Trust)];verify.restype=c.c_int32
    data=dll.WTHelperProvDataFromStateData;data.argtypes=[ptr];data.restype=ptr
    signer=dll.WTHelperGetProvSignerFromChain;signer.argtypes=[ptr,u32,c.c_int32,u32];signer.restype=c.POINTER(Signer)
    guid=Guid(0x00aac56b,0xcd44,0x11d0,(c.c_ubyte*8)(0x8c,0xc2,0,0xc0,0x4f,0xc2,0x95,0xee))
    file=File(c.sizeof(File),str(path),None,None)
    # Cache only; no additional revocation fetch. Full publisher release checks
    # must independently establish current revocation status before distribution.
    trust=Trust(c.sizeof(Trust),None,None,2,0,1,c.pointer(file),1,None,None,0x1000|0x10|0x2000,0,None)
    try:
        result=verify(ptr(-1),c.byref(guid),c.byref(trust))
        require(result==0,'Authenticode chain/integrity rejected: %08x'%(result&0xffffffff))
        provider=data(trust.state);require(provider,'Windows verified signer state absent')
        primary=signer(provider,0,0,0);require(bool(primary),'Windows verified signer absent')
        info=primary.contents
        require(info.error==0 and info.count>0 and bool(info.chain) and bool(info.chain.contents.cert),'Invalid verified signer chain')
        require(info.counter_count>0,'Verified Authenticode timestamp required')
        counter=signer(provider,0,1,0);require(bool(counter) and counter.contents.error==0 and counter.contents.count>0,'Invalid timestamp countersigner')
        cert=info.chain.contents.cert.contents
        require(bool(cert.encoded) and 0<cert.length<=1024*1024,'Invalid signer DER')
        certificate=hashlib.sha256(c.string_at(cert.encoded,cert.length)).hexdigest()
    finally:
        if trust.state:trust.action=2;verify(ptr(-1),c.byref(guid),c.byref(trust))
    require(hashlib.sha256(path.read_bytes()).hexdigest()==before,'Executable changed during signature verification')
    return dict(policy=POLICY,executable_sha256=before,signer_certificate_sha256=certificate,timestamp_verified=True)

def verify(path,expected_certificate):
    report=inspect(path)
    require(report['signer_certificate_sha256']==expected_certificate,'Authenticode publisher differs from approved certificate')
    return report
