//! OS child-process tree guard so the Python bridge and its background servers
//! never outlive the desktop shell on crashes or forced termination.

use std::process::Child;

#[cfg(windows)]
mod imp {
    use std::{ffi::c_void, mem::size_of, os::windows::io::AsRawHandle, process::Child, ptr};

    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: i32 = 9;
    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x0000_2000;

    #[repr(C)]
    #[derive(Default)]
    struct JobObjectBasicLimitInformation {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    #[repr(C)]
    #[derive(Default)]
    struct IoCounters {
        read_operation_count: u64,
        write_operation_count: u64,
        other_operation_count: u64,
        read_transfer_count: u64,
        write_transfer_count: u64,
        other_transfer_count: u64,
    }

    #[repr(C)]
    #[derive(Default)]
    pub(super) struct JobObjectExtendedLimitInformation {
        basic_limit_information: JobObjectBasicLimitInformation,
        io_info: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_used: usize,
        peak_job_memory_used: usize,
    }

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn CreateJobObjectW(attributes: *mut c_void, name: *const u16) -> *mut c_void;
        fn SetInformationJobObject(
            job: *mut c_void,
            info_class: i32,
            info: *const c_void,
            info_length: u32,
        ) -> i32;
        fn AssignProcessToJobObject(job: *mut c_void, process: *mut c_void) -> i32;
        fn CloseHandle(object: *mut c_void) -> i32;
    }

    pub(crate) struct ChildProcessJob {
        handle: *mut c_void,
    }

    // Kernel Job Object handles are safe to hold behind DesktopState's mutex and close from any thread.
    unsafe impl Send for ChildProcessJob {}
    unsafe impl Sync for ChildProcessJob {}

    impl ChildProcessJob {
        pub(crate) fn assign_child(child: &Child) -> Result<Self, String> {
            let job = unsafe { CreateJobObjectW(ptr::null_mut(), ptr::null()) };
            if job.is_null() {
                return Err(std::io::Error::last_os_error().to_string());
            }
            let guard = Self { handle: job };

            let mut info = JobObjectExtendedLimitInformation::default();
            info.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let configured = unsafe {
                SetInformationJobObject(
                    guard.handle,
                    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                    (&raw const info).cast::<c_void>(),
                    size_of::<JobObjectExtendedLimitInformation>() as u32,
                )
            };
            if configured == 0 {
                return Err(std::io::Error::last_os_error().to_string());
            }

            let assigned = unsafe {
                AssignProcessToJobObject(guard.handle, child.as_raw_handle().cast::<c_void>())
            };
            if assigned == 0 {
                return Err(std::io::Error::last_os_error().to_string());
            }

            Ok(guard)
        }
    }

    impl Drop for ChildProcessJob {
        fn drop(&mut self) {
            if !self.handle.is_null() {
                unsafe {
                    let _ = CloseHandle(self.handle);
                }
                self.handle = ptr::null_mut();
            }
        }
    }

    #[cfg(test)]
    pub(crate) fn extended_limit_info_size() -> usize {
        size_of::<JobObjectExtendedLimitInformation>()
    }
}

#[cfg(not(windows))]
mod imp {
    use std::process::Child;

    pub(crate) struct ChildProcessJob;

    impl ChildProcessJob {
        pub(crate) fn assign_child(_child: &Child) -> Result<Self, String> {
            Ok(Self)
        }
    }
}

pub(crate) use imp::ChildProcessJob;
#[cfg(all(test, windows))]
pub(crate) use imp::extended_limit_info_size;

pub(crate) fn assign_child_to_job(child: &Child) -> Result<ChildProcessJob, String> {
    ChildProcessJob::assign_child(child)
}
