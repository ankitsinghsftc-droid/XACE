use anyhow::{ensure, Result};
use std::process::Child;
#[cfg(windows)]
mod platform {
    use super::*;
    use std::{ffi::c_void, os::windows::io::AsRawHandle};
    #[repr(C)]
    #[derive(Default)]
    struct Basic {
        process_time: i64,
        job_time: i64,
        flags: u32,
        min: usize,
        max: usize,
        active: u32,
        affinity: usize,
        priority: u32,
        scheduling: u32,
    }
    #[repr(C)]
    #[derive(Default)]
    struct Extended {
        basic: Basic,
        io: [u64; 6],
        process_memory: usize,
        job_memory: usize,
        peak_process: usize,
        peak_job: usize,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(attributes: *const c_void, name: *const u16) -> *mut c_void;
        fn SetInformationJobObject(
            job: *mut c_void,
            class: i32,
            data: *const c_void,
            size: u32,
        ) -> i32;
        fn AssignProcessToJobObject(job: *mut c_void, process: *mut c_void) -> i32;
        fn CloseHandle(handle: *mut c_void) -> i32;
    }
    pub struct Job(*mut c_void);
    impl Job {
        pub fn own(child: &Child) -> Result<Self> {
            let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
            ensure!(!handle.is_null(), "Cannot create process ownership job");
            let job = Self(handle);
            let mut limits = Extended::default();
            limits.basic.flags = 0x2000;
            ensure!(
                unsafe {
                    SetInformationJobObject(
                        handle,
                        9,
                        &limits as *const _ as *const c_void,
                        std::mem::size_of::<Extended>() as u32,
                    )
                } != 0,
                "Cannot set process cleanup policy"
            );
            ensure!(
                unsafe { AssignProcessToJobObject(handle, child.as_raw_handle()) } != 0,
                "Cannot own Player process: {}",
                std::io::Error::last_os_error()
            );
            Ok(job)
        }
    }
    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}
#[cfg(not(windows))]
mod platform {
    use super::*;
    pub struct Job;
    impl Job {
        pub fn own(_: &Child) -> Result<Self> {
            anyhow::bail!("Windows x86_64 required")
        }
    }
}
pub use platform::Job;
