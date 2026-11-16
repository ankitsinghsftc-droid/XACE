//! Exact v1 build evidence retained under a versioned, publisher-pinned derivation.
use anyhow::{ensure,Context,Result};
use serde::{Deserialize,Serialize};
use serde_json::Value;
use std::path::Path;

#[derive(Clone,Deserialize,Serialize)]
#[serde(deny_unknown_fields)]
pub struct PublisherPolicy { pub schema:String,pub trust_policy:String,pub allowed_signer_certificate_sha256:Vec<String> }
fn hash(value:&str)->Result<()> {ensure!(value.len()==64 && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),"SHA256 required");Ok(())}
impl PublisherPolicy {
    pub fn validate(&self)->Result<()> {
        ensure!(self.schema=="xace.publisher_policy.v1" && self.trust_policy==crate::authenticode::POLICY,"Unsupported publisher trust policy");
        ensure!(!self.allowed_signer_certificate_sha256.is_empty() && self.allowed_signer_certificate_sha256.windows(2).all(|w|w[0]<w[1]),"Sorted approved publisher certificates required");
        for cert in &self.allowed_signer_certificate_sha256 {hash(cert)?;} Ok(())
    }
}
fn canonical_digest(value:&Value)->Result<String> {
    let json=serde_json::to_string(value)?;let mut ascii=String::new();
    for ch in json.chars() {if ch as u32>=127 {let mut units=[0u16;2];for unit in ch.encode_utf16(&mut units){ascii.push_str(&format!("\\u{unit:04x}"));}} else {ascii.push(ch);}}
    Ok(crate::distribution::digest(ascii.as_bytes()))
}
pub fn validate(executor:&Value)->Result<()> {
    let d=executor["derivation"].as_object().context("Exact signing derivation required")?;
    let fields=["schema","unsigned_receipt","unsigned_receipt_sha256","signer_certificate_sha256","trust_policy","unsigned_length","unsigned_pe_checksum"];
    ensure!(d.len()==fields.len() && fields.iter().all(|f|d.contains_key(*f)),"Exact signing derivation required");
    ensure!(d["schema"]=="xace.authenticode_derivation.v1" && d["trust_policy"]==crate::authenticode::POLICY,"Unsupported signing derivation");
    let original=&d["unsigned_receipt"];ensure!(original["schema"]=="xace.native_executor_build.v1","Original v1 unsigned receipt required");
    crate::native_release::validate_creator(original)?;
    ensure!(d["unsigned_receipt_sha256"]==canonical_digest(original)?,"Original unsigned receipt identity changed");
    hash(d["signer_certificate_sha256"].as_str().context("Signer certificate required")?)?;
    let final_hash=executor["executable_sha256"].as_str().context("Signed identity required")?;hash(final_hash)?;
    ensure!(original["executable_sha256"]!=final_hash,"Distinct unsigned and signed identities required");
    ensure!(d["unsigned_length"].as_u64().is_some_and(|n|(256..=128*1024*1024).contains(&n)) && d["unsigned_pe_checksum"].as_u64().is_some_and(|n|n<=u32::MAX as u64),"Unsigned PE layout identity required");
    let mut expected=original.clone();expected["schema"]="xace.native_executor_build.v2".into();expected["executable_sha256"]=final_hash.into();expected["shipping"]["required_files"]["runtime/xace_runtime.exe"]=final_hash.into();expected["derivation"]=executor["derivation"].clone();
    ensure!(expected==*executor,"Signing cannot alter source/build/system/capability/compatibility contracts");
    let builds=original["build"]["independent_outputs"].as_array().context("Original independent builds required")?;
    ensure!(builds.len()==2 && builds[0]["build_id"].as_str().is_some_and(|s|!s.is_empty()) && builds[1]["build_id"].as_str().is_some_and(|s|!s.is_empty()) && builds[0]["build_id"]!=builds[1]["build_id"] && builds.iter().all(|b|b["executable_sha256"]==original["executable_sha256"]),"Original executable not reproduced");
    Ok(())
}
fn u16_at(raw:&[u8],offset:usize)->Result<u16> {Ok(u16::from_le_bytes(raw.get(offset..offset+2).context("Truncated PE")?.try_into()?))}
fn u32_at(raw:&[u8],offset:usize)->Result<u32> {Ok(u32::from_le_bytes(raw.get(offset..offset+4).context("Truncated PE")?.try_into()?))}
pub fn verify_pe(raw:&[u8],derivation:&Value)->Result<()> {
    ensure!((256..=128*1024*1024).contains(&raw.len()) && raw.get(..2)==Some(b"MZ"),"Windows PE bytes required");
    let pe=u32_at(raw,0x3c)? as usize;ensure!(pe>=64 && pe+24+152<=raw.len() && raw.get(pe..pe+4)==Some(b"PE\0\0"),"Invalid PE header");
    ensure!(u16_at(raw,pe+4)?==0x8664,"AMD64 PE required");let optional=pe+24;let size=u16_at(raw,pe+20)? as usize;
    ensure!(size>=152 && optional+size<=raw.len() && u16_at(raw,optional)?==0x20b && u32_at(raw,optional+108)?>=5,"PE32+ optional header required");
    let checksum=optional+64;let security=optional+112+4*8;
    let length=derivation["unsigned_length"].as_u64().context("Unsigned length required")? as usize;
    let original_checksum=derivation["unsigned_pe_checksum"].as_u64().context("Unsigned checksum required")?;
    ensure!(length>=security+8 && length<=raw.len() && original_checksum<=u32::MAX as u64,"Invalid unsigned PE layout");
    let offset=u32_at(raw,security)? as usize;let size=u32_at(raw,security+4)? as usize;
    ensure!(offset%8==0 && length<=offset && offset<length+8 && size>=8 && offset.checked_add(size)==Some(raw.len()),"Only an appended aligned certificate table is permitted");
    ensure!(raw[length..offset].iter().all(|b|*b==0),"Nonzero added PE padding");
    let cert_length=u32_at(raw,offset)? as usize;
    ensure!(u16_at(raw,offset+4)?==0x200 && u16_at(raw,offset+6)?==2 && cert_length>=8 && cert_length<=size && size-cert_length<8 && raw[offset+cert_length..].iter().all(|b|*b==0),"One standard PKCS certificate table required");
    let mut restored=raw[..length].to_vec();restored[checksum..checksum+4].copy_from_slice(&(original_checksum as u32).to_le_bytes());restored[security..security+8].fill(0);
    ensure!(derivation["unsigned_receipt"]["executable_sha256"]==crate::distribution::digest(&restored),"Signed bytes do not derive from reproduced unsigned PE");Ok(())
}
pub fn verify(executor:&Value,policy:&PublisherPolicy,path:&Path,bytes:&[u8])->Result<()> {
    validate(executor)?;policy.validate()?;
    let cert=executor["derivation"]["signer_certificate_sha256"].as_str().context("Signer certificate required")?;
    ensure!(policy.allowed_signer_certificate_sha256.iter().any(|c|c==cert),"Signed executor publisher is not approved by host");
    verify_pe(bytes,&executor["derivation"])?;
    let signature=crate::authenticode::verify(path,cert)?;
    ensure!(executor["executable_sha256"]==signature.executable_sha256,"Signed executor changed during admission");Ok(())
}

#[derive(Clone,Deserialize,Serialize)]
#[serde(deny_unknown_fields)]
pub struct LauncherDerivation {
    pub schema:String,pub unsigned_sha256:String,pub executable_sha256:String,
    pub unsigned_length:u64,pub unsigned_pe_checksum:u64,pub signer_certificate_sha256:String,
}
pub fn verify_launcher(root:&Path,derivation:&LauncherDerivation,policy:&PublisherPolicy,resources:&[crate::distribution::FileRecord])->Result<()> {
    ensure!(derivation.schema=="xace.signed_launcher.v1","Versioned launcher derivation required");
    for value in [&derivation.unsigned_sha256,&derivation.executable_sha256,&derivation.signer_certificate_sha256] {hash(value)?;}
    ensure!(derivation.unsigned_sha256!=derivation.executable_sha256 && policy.allowed_signer_certificate_sha256.contains(&derivation.signer_certificate_sha256),"Unapproved signed launcher identity");
    ensure!(resources.iter().any(|r|r.path=="xace-player-launcher.exe" && r.sha256==derivation.executable_sha256),"Signed launcher missing from release closure");
    let path=root.join("xace-player-launcher.exe");let bytes=std::fs::read(&path)?;
    ensure!(crate::distribution::digest(&bytes)==derivation.executable_sha256,"Signed launcher bytes changed");
    let d=serde_json::json!({"unsigned_receipt":{"executable_sha256":derivation.unsigned_sha256},"unsigned_length":derivation.unsigned_length,"unsigned_pe_checksum":derivation.unsigned_pe_checksum});
    verify_pe(&bytes,&d)?;
    let signature=crate::authenticode::verify(&path,&derivation.signer_certificate_sha256)?;
    ensure!(signature.executable_sha256==derivation.executable_sha256,"Launcher changed during signature admission");Ok(())
}
