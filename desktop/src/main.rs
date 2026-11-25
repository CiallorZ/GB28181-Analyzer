#![windows_subsystem = "windows"]

use std::{io::{self, BufRead, BufReader}, mem::{size_of, zeroed}, os::windows::{io::{AsRawHandle, FromRawHandle, OwnedHandle}, process::CommandExt}, process::{Command, Stdio}, ptr, sync::{atomic::{AtomicBool, Ordering}, mpsc}, thread, time::Duration};
use tauri::{WebviewUrl, WebviewWindowBuilder};
use windows_sys::Win32::{
    System::JobObjects::*,
    UI::WindowsAndMessaging::{
        MessageBoxW, IDYES, MB_ICONERROR, MB_ICONQUESTION, MB_YESNO,
    },
};

static ANALYSIS_BUSY: AtomicBool = AtomicBool::new(false);

#[tauri::command]
fn set_analysis_busy(busy: bool) {
    ANALYSIS_BUSY.store(busy, Ordering::SeqCst);
}

#[tauri::command]
fn pick_executable(window: tauri::Window, title: String) -> Option<String> {
    // 以主窗口为父窗口，对话框才会以模态方式出现在窗口前面。
    let mut dialog = rfd::FileDialog::new().set_title(&title).set_parent(&window);
    if let Some(profile) = std::env::var_os("USERPROFILE") {
        let desktop = std::path::PathBuf::from(profile).join("Desktop");
        if desktop.is_dir() {
            dialog = dialog.set_directory(desktop);
        }
    }
    dialog
        .add_filter("可执行文件", &["exe"])
        .pick_file()
        .map(|path| path.display().to_string())
}

fn start() -> Result<(), Box<dyn std::error::Error>> {
    let engine = std::env::current_exe()?.with_file_name("engine").join("AnalyzerEngine.exe");
    // Closing our last job handle also terminates any active TShark/FFmpeg descendants.
    let job = unsafe {
        let handle = CreateJobObjectW(ptr::null(), ptr::null());
        if handle.is_null() { return Err(io::Error::last_os_error().into()); }
        let job = OwnedHandle::from_raw_handle(handle);
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(handle, JobObjectExtendedLimitInformation, &info as *const _ as _, size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32) == 0 {
            return Err(io::Error::last_os_error().into());
        }
        job
    };
    let mut cmd = Command::new(engine);
    cmd.args(["--desktop-child", "--no-browser", "--port", "0"]);
    cmd.args(std::env::args_os().skip(1));
    let mut child = cmd.creation_flags(0x08000000).stdin(Stdio::piped()).stdout(Stdio::piped()).spawn()?;
    if unsafe { AssignProcessToJobObject(job.as_raw_handle(), child.as_raw_handle()) } == 0 {
        let err = io::Error::last_os_error();
        let _ = child.kill();
        return Err(err.into());
    }
    let stdout = child.stdout.take().unwrap();
    let (tx, rx) = mpsc::sync_channel(1);
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(port) = line.strip_prefix("DESKTOP_READY=").and_then(|s| s.parse::<u16>().ok()) {
                let _ = tx.send(port);
            }
        }
    });
    let port = rx.recv_timeout(Duration::from_secs(45)).map_err(|_| "分析服务启动失败，请检查是否已经打开工作台，以及数据目录是否可写。")?;
    let url: tauri::Url = format!("http://127.0.0.1:{port}/").parse()?;
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![set_analysis_busy, pick_executable])
        .build(tauri::generate_context!())?;
    let origin = url.origin();
    // Tauri's work area excludes the taskbar and is reported in physical pixels.
    let (width, height) = app.primary_monitor().ok().flatten().map_or((1060., 680.), |monitor| {
        let usable = monitor.work_area().size.to_logical::<f64>(monitor.scale_factor());
        ((usable.width * 0.92).min(1480.), (usable.height * 0.91).min(920.))
    });
    let window = WebviewWindowBuilder::new(&app, "main", WebviewUrl::External(url))
        .title("GB28181 Analyzer · 视联网分析工作台")
        .inner_size(width, height)
        .min_inner_size(width.min(520.), height.min(360.))
        .center()
        .disable_drag_drop_handler()
        .on_navigation(move |target| target.origin() == origin)
        .build()?;
    window.on_window_event(|event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            if ANALYSIS_BUSY.load(Ordering::SeqCst) {
                let text: Vec<u16> = "分析正在进行，关闭窗口会终止任务。仍要退出吗？\0"
                    .encode_utf16().collect();
                let title: Vec<u16> = "GB28181 Analyzer\0".encode_utf16().collect();
                let choice = unsafe {
                    MessageBoxW(ptr::null_mut(), text.as_ptr(), title.as_ptr(),
                                MB_YESNO | MB_ICONQUESTION)
                };
                if choice != IDYES {
                    api.prevent_close();
                }
            }
        }
    });
    app.run_return(|_, _| {});
    drop(child.stdin.take());
    for _ in 0..30 {
        if child.try_wait()?.is_some() { break; }
        thread::sleep(Duration::from_millis(100));
    }
    drop(job);
    Ok(())
}

fn main() {
    if let Err(error) = start() {
        let msg: Vec<u16> = format!("{error}\n请确认已安装 Microsoft Edge WebView2 Runtime。\0").encode_utf16().collect();
        let title: Vec<u16> = "GB28181 Analyzer\0".encode_utf16().collect();
        unsafe { MessageBoxW(ptr::null_mut(), msg.as_ptr(), title.as_ptr(), MB_ICONERROR); }
        std::process::exit(1);
    }
}
