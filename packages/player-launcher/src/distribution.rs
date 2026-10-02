use anyhow::{bail, ensure, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    fs,
    path::{Component, Path, PathBuf},
};

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FileRecord {
    pub path: String,
    pub sha256: String,
    pub size: u64,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Distribution {
    pub schema: String,
    pub platform: String,
    pub version: String,
    pub gameplay_hash: String,
    pub cgs_hash: String,
    pub files: Vec<FileRecord>,
}
pub fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
pub fn safe_path(value: &str) -> Result<PathBuf> {
    ensure!(
        !value.is_empty() && !value.contains(['\\', ':']) && !value.starts_with('/'),
        "unsafe distribution path"
    );
    ensure!(
        value
            .split('/')
            .all(|p| !p.is_empty() && p != "." && p != ".." && !p.ends_with([' ', '.'])),
        "unsafe distribution component"
    );
    let path = PathBuf::from(value);
    ensure!(
        path.components().all(|c| matches!(c, Component::Normal(_))),
        "unsafe distribution path"
    );
    Ok(path)
}
fn plain(path: &Path) -> Result<()> {
    let meta = fs::symlink_metadata(path)?;
    ensure!(
        !meta.file_type().is_symlink(),
        "distribution links are not supported"
    );
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        ensure!(
            meta.file_attributes() & 0x400 == 0,
            "distribution reparse points are not supported"
        );
    }
    Ok(())
}
pub fn verified(root: &Path, expected: &str) -> Result<Distribution> {
    ensure!(
        expected.len() == 64 && expected.bytes().all(|b| b.is_ascii_hexdigit()),
        "invalid trusted digest"
    );
    plain(root)?;
    let manifest_path = root.join("distribution.json");
    plain(&manifest_path)?;
    let bytes = fs::read(manifest_path)?;
    ensure!(
        bytes.len() <= 4 * 1024 * 1024 && digest(&bytes) == expected,
        "Distribution changed. Restore the verified download and retry."
    );
    let manifest: Distribution = serde_json::from_slice(&bytes)?;
    ensure!(
        manifest.schema == "xace.player.distribution.v1" && manifest.platform == "windows-x86_64",
        "unsupported Player distribution"
    );
    ensure!(
        !manifest.files.is_empty() && manifest.files.len() <= 8192,
        "invalid distribution file count"
    );
    let mut names = BTreeSet::new();
    let mut total = 0u64;
    for record in &manifest.files {
        let rel = safe_path(&record.path)?;
        ensure!(
            names.insert(record.path.to_lowercase()),
            "duplicate distribution path"
        );
        total = total
            .checked_add(record.size)
            .context("distribution size overflow")?;
        ensure!(
            record.size <= 512 * 1024 * 1024 && total <= 2 * 1024 * 1024 * 1024,
            "distribution size limit"
        );
        let mut path = root.to_path_buf();
        for part in rel.components() {
            path.push(part);
            plain(&path)?;
        }
        ensure!(
            fs::metadata(&path)?.len() == record.size && digest(&fs::read(path)?) == record.sha256,
            "Installed file changed: {}. Restore the verified download and retry.",
            record.path
        );
    }
    for required in [
        "xace-player.exe",
        "xace-player.pck",
        "package/playable.manifest.json",
        "package/runtime/xace_runtime.exe",
        "NOTICES.txt",
        "admission.json",
    ] {
        ensure!(
            names.contains(&required.to_lowercase()),
            "missing distribution file {required}"
        );
    }
    Ok(manifest)
}

pub struct InstallLock {
    path: PathBuf,
    file: Option<fs::File>,
}
impl InstallLock {
    pub fn acquire(root: &Path) -> Result<Self> {
        fs::create_dir_all(root)
            .context("Cannot install here. Choose a writable folder and retry.")?;
        plain(root)?;
        let path = root.join("install.lock");
        let mut options = fs::OpenOptions::new();
        options.write(true).create(true);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.share_mode(0);
        }
        let result = options.open(&path);
        if result.is_err() {
            bail!(
                "Another install owns this folder, or it is not writable. Retry after it finishes."
            );
        }
        Ok(Self {
            path,
            file: Some(result.unwrap()),
        })
    }
}
impl Drop for InstallLock {
    fn drop(&mut self) {
        self.file.take();
        let _ = fs::remove_file(&self.path);
    }
}

// Install stages immutable bytes only. The active pointer changes after readiness.
pub fn materialize(source: &Path, install: &Path, expected: &str) -> Result<PathBuf> {
    let manifest = verified(source, expected)?;
    let _lock = InstallLock::acquire(install)?;
    let versions = install.join("versions");
    fs::create_dir_all(&versions)?;
    plain(&versions)?;
    let target = versions.join(expected);
    if target.exists() && verified(&target, expected).is_ok() {
        return Ok(target);
    }
    let stage = versions.join(format!("stage-{}", uuid::Uuid::new_v4()));
    fs::create_dir(&stage)?;
    let result = (|| -> Result<()> {
        for record in &manifest.files {
            let rel = safe_path(&record.path)?;
            let dest = stage.join(&rel);
            fs::create_dir_all(dest.parent().unwrap())?;
            fs::copy(source.join(rel), dest)?;
        }
        fs::copy(
            source.join("distribution.json"),
            stage.join("distribution.json"),
        )?;
        verified(&stage, expected)?;
        if target.exists() {
            let quarantine = versions.join(format!("damaged-{}", uuid::Uuid::new_v4()));
            fs::rename(&target, &quarantine)?;
            if let Err(error) = fs::rename(&stage, &target) {
                let _ = fs::rename(&quarantine, &target);
                return Err(error.into());
            }
        } else {
            fs::rename(&stage, &target)?;
        }
        Ok(())
    })();
    if result.is_err() && stage.parent() == Some(versions.as_path()) {
        let _ = fs::remove_dir_all(&stage);
    }
    result?;
    Ok(target)
}

pub fn activate(install: &Path, expected: &str) -> Result<()> {
    let _lock = InstallLock::acquire(install)?;
    let temp = install.join(format!("active-{}.tmp", uuid::Uuid::new_v4()));
    fs::write(
        &temp,
        serde_json::to_vec(
            &serde_json::json!({"schema":"xace.player.install.v1","version_digest":expected}),
        )?,
    )?;
    replace(&temp, &install.join("active.json"))
}
#[cfg(windows)]
fn replace(source: &Path, target: &Path) -> Result<()> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn MoveFileExW(a: *const u16, b: *const u16, flags: u32) -> i32;
    }
    let a: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let b: Vec<u16> = target.as_os_str().encode_wide().chain(Some(0)).collect();
    ensure!(
        unsafe { MoveFileExW(a.as_ptr(), b.as_ptr(), 9) } != 0,
        "Could not activate install: {}",
        std::io::Error::last_os_error()
    );
    Ok(())
}
#[cfg(not(windows))]
fn replace(source: &Path, target: &Path) -> Result<()> {
    fs::rename(source, target)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unsafe_paths() {
        for path in ["../x", "a/../x", "C:/x", "a\\b", "/a", "a//b", "a./b"] {
            assert!(safe_path(path).is_err(), "{path}");
        }
        assert!(safe_path("package/world.json").is_ok());
    }
    #[test]
    fn invalid_trust_is_rejected_before_files() {
        assert!(verified(Path::new("missing"), "bad").is_err());
    }
}
