#![windows_subsystem = "windows"]

use std::{
    io::{self, BufRead, BufReader},
    mem::{size_of, zeroed},
    os::windows::{
        io::{AsRawHandle, FromRawHandle, OwnedHandle},
        process::CommandExt,
    },
    process::{Command, Stdio},
    ptr,
    sync::mpsc,
    thread,
    time::Duration,
};

use windows_sys::Win32::{
    System::JobObjects::*,
    UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR},
};

fn start() -> Result<(), Box<dyn std::error::Error>> {
    let engine = std::env::current_exe()?
        .with_file_name("engine")
        .join("AnalyzerEngine.exe");
    // Closing our last job handle also terminates any active TShark/FFmpeg descendants.
    let job = unsafe {
        let handle = CreateJobObjectW(ptr::null(), ptr::null());
        if handle.is_null() {
            return Err(io::Error::last_os_error().into());
        }
        let job = OwnedHandle::from_raw_handle(handle);
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            &info as *const _ as _,
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        ) == 0
        {
            return Err(io::Error::last_os_error().into());
        }
        job
    };
    let mut cmd = Command::new(engine);
    cmd.args(["--desktop-child", "--no-browser", "--port", "0"]);
    cmd.args(std::env::args_os().skip(1));
    let mut child = cmd
        .creation_flags(0x08000000)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()?;
    if unsafe { AssignProcessToJobObject(job.as_raw_handle(), child.as_raw_handle()) } == 0 {
        let err = io::Error::last_os_error();
        let _ = child.kill();
        return Err(err.into());
    }
    let stdout = child.stdout.take().unwrap();
    let (tx, rx) = mpsc::sync_channel(1);
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(port) = line
                .strip_prefix("DESKTOP_READY=")
                .and_then(|s| s.parse::<u16>().ok())
            {
                let _ = tx.send(port);
            }
        }
    });
    let port = rx
        .recv_timeout(Duration::from_secs(45))
        .map_err(|_| "分析服务启动失败，请检查是否已经打开工作台，以及数据目录是否可写。")?;
    let host = std::env::current_exe()?
        .with_file_name("shell")
        .join("AnalyzerShell.exe");
    let mut window = Command::new(&host)
        .current_dir(host.parent().unwrap())
        .env("GB28181_ENGINE_PORT", port.to_string())
        .spawn()?;
    if unsafe { AssignProcessToJobObject(job.as_raw_handle(), window.as_raw_handle()) } == 0 {
        let error = io::Error::last_os_error();
        let _ = window.kill();
        return Err(error.into());
    }
    let status = window.wait()?;
    drop(child.stdin.take());
    for _ in 0..30 {
        if child.try_wait()?.is_some() {
            break;
        }
        thread::sleep(Duration::from_millis(100));
    }
    drop(job);
    if !status.success() {
        return Err("Native Shell 未正常退出".into());
    }
    Ok(())
}

fn main() {
    if let Err(error) = start() {
        let msg: Vec<u16> = format!("{error}\n请确认已安装 Microsoft Edge WebView2 Runtime。\0")
            .encode_utf16()
            .collect();
        let title: Vec<u16> = "GB28181 Analyzer\0".encode_utf16().collect();
        unsafe {
            MessageBoxW(ptr::null_mut(), msg.as_ptr(), title.as_ptr(), MB_ICONERROR);
        }
        std::process::exit(1);
    }
}
