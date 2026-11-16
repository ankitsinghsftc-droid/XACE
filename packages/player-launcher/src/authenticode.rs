//! Read-only OS Authenticode verification; no shell, target execution or store writes.
use anyhow::{ensure, Result};
use serde::Serialize;
use std::path::Path;

pub const POLICY: &str = "windows_authenticode_cached_chain.v1";
#[derive(Serialize)]
pub struct Signature {
    pub policy: &'static str,
    pub executable_sha256: String,
    pub signer_certificate_sha256: String,
    pub timestamp_verified: bool,
}
#[cfg(windows)]
mod windows {
    use super::*;
    use std::{ffi::c_void, mem::size_of, os::windows::ffi::OsStrExt, ptr};
    #[repr(C)] struct Guid { a:u32,b:u16,c:u16,d:[u8;8] }
    #[repr(C)] struct File { size:u32,path:*const u16,handle:*mut c_void,subject:*mut c_void }
    #[repr(C)] struct Trust { size:u32,policy:*mut c_void,sip:*mut c_void,ui:u32,revocation:u32,choice:u32,file:*mut File,action:u32,state:*mut c_void,url:*const u16,flags:u32,context:u32,settings:*mut c_void }
    #[repr(C)] struct Cert { encoding:u32,encoded:*const u8,length:u32,info:*mut c_void,store:*mut c_void }
    #[repr(C)] struct ProviderCert { size:u32,cert:*const Cert }
    #[repr(C)] struct Signer { size:u32,time:[u32;2],count:u32,chain:*const ProviderCert,kind:u32,info:*mut c_void,error:u32,counter_count:u32,counters:*mut c_void,context:*mut c_void }
    #[link(name="wintrust")]
    extern "system" {
        fn WinVerifyTrust(window:*mut c_void,action:*const Guid,data:*mut Trust)->i32;
        fn WTHelperProvDataFromStateData(state:*mut c_void)->*mut c_void;
        fn WTHelperGetProvSignerFromChain(data:*mut c_void,index:u32,counter:i32,counter_index:u32)->*const Signer;
    }
    struct State { data:Trust, action:Guid }
    impl Drop for State {
        fn drop(&mut self) { if !self.data.state.is_null() { self.data.action=2; unsafe {WinVerifyTrust(usize::MAX as *mut c_void,&self.action,&mut self.data);} } }
    }
    pub fn inspect(path:&Path)->Result<Signature> {
        let before=crate::distribution::digest(&std::fs::read(path)?);
        let path=path.canonicalize()?;
        let mut wide:Vec<u16>=path.as_os_str().encode_wide().collect();
        ensure!(!wide.contains(&0),"NUL in signature path");wide.push(0);
        let mut file=File{size:size_of::<File>() as u32,path:wide.as_ptr(),handle:ptr::null_mut(),subject:ptr::null_mut()};
        let mut state=State{action:Guid{a:0x00aac56b,b:0xcd44,c:0x11d0,d:[0x8c,0xc2,0,0xc0,0x4f,0xc2,0x95,0xee]},data:Trust{size:size_of::<Trust>() as u32,policy:ptr::null_mut(),sip:ptr::null_mut(),ui:2,revocation:0,choice:1,file:&mut file,action:1,state:ptr::null_mut(),url:ptr::null(),flags:0x1000|0x10|0x2000,context:0,settings:ptr::null_mut()}};
        // All provider pointers are owned by this successful WinVerifyTrust state;
        // copy the bounded DER digest before State::drop closes that state.
        let certificate=unsafe {
            let code=WinVerifyTrust(usize::MAX as *mut c_void,&state.action,&mut state.data);
            ensure!(code==0,"Authenticode chain/integrity rejected: {:08x}",code as u32);
            let provider=WTHelperProvDataFromStateData(state.data.state);ensure!(!provider.is_null(),"Verified signer state absent");
            let primary=WTHelperGetProvSignerFromChain(provider,0,0,0);ensure!(!primary.is_null(),"Verified signer absent");
            let signer=&*primary;ensure!(signer.error==0 && signer.count>0 && !signer.chain.is_null() && !(*signer.chain).cert.is_null(),"Invalid verified signer chain");
            ensure!(signer.counter_count>0,"Verified Authenticode timestamp required");
            let counter=WTHelperGetProvSignerFromChain(provider,0,1,0);ensure!(!counter.is_null() && (*counter).error==0 && (*counter).count>0,"Invalid timestamp countersigner");
            let cert=&*(*signer.chain).cert;ensure!(!cert.encoded.is_null() && cert.length>0 && cert.length<=1024*1024,"Invalid signer DER");
            crate::distribution::digest(std::slice::from_raw_parts(cert.encoded,cert.length as usize))
        };
        ensure!(crate::distribution::digest(&std::fs::read(&path)?)==before,"Executable changed during signature verification");
        Ok(Signature{policy:POLICY,executable_sha256:before,signer_certificate_sha256:certificate,timestamp_verified:true})
    }
}
pub fn inspect(path:&Path)->Result<Signature> {
    #[cfg(windows)] {windows::inspect(path)}
    #[cfg(not(windows))] {let _=path;anyhow::bail!("Windows Authenticode verification required")}
}
pub fn verify(path:&Path,expected_certificate:&str)->Result<Signature> {
    let result=inspect(path)?;
    ensure!(result.signer_certificate_sha256==expected_certificate,"Authenticode publisher differs from approved certificate");Ok(result)
}
