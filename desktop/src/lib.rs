//! Bounded Annex B marker scan. Offsets match the reference parser, including trailing prefixes.
use std::slice;

#[repr(C)]
pub struct Marker {
    offset: usize,
    prefix: usize,
}

/// # Safety
/// data must reference len readable bytes and out must hold capacity writable markers.
/// The two buffers must not alias. The caller resumes at the last marker plus its prefix.
#[no_mangle]
pub unsafe extern "C" fn gb_scan_annex_b(
    data: *const u8,
    len: usize,
    start: usize,
    out: *mut Marker,
    capacity: usize,
) -> usize {
    if data.is_null() || out.is_null() || start >= len || capacity == 0 {
        return 0;
    }
    let bytes = unsafe { slice::from_raw_parts(data, len) };
    let mut i = start;
    let mut count = 0;
    while i < len.saturating_sub(3) {
        let prefix = if bytes[i..i + 3] == [0, 0, 1] {
            3
        } else if bytes[i..i + 4] == [0, 0, 0, 1] {
            4
        } else {
            i += 1;
            continue;
        };
        unsafe { out.add(count).write(Marker { offset: i, prefix }) };
        count += 1;
        if count == capacity {
            break;
        }
        i += prefix;
    }
    count
}
/// Opens a native Windows file dialog. Returns the selected UTF-16 path length,
/// zero on cancellation, or -1 when Windows reports an error.
///
/// # Safety
/// out must hold capacity writable UTF-16 code units, initially zeroed.
#[no_mangle]
pub unsafe extern "C" fn gb_pick_executable(out: *mut u16, capacity: u32) -> i32 {
    use windows_sys::Win32::UI::Controls::Dialogs::*;
    if out.is_null() || capacity < 2 {
        return -1;
    }
    let filter: Vec<u16> = "Windows 可执行文件 (*.exe)\0*.exe\0\0"
        .encode_utf16()
        .collect();
    let mut dialog: OPENFILENAMEW = unsafe { std::mem::zeroed() };
    dialog.lStructSize = std::mem::size_of::<OPENFILENAMEW>() as u32;
    dialog.lpstrFilter = filter.as_ptr();
    dialog.lpstrFile = out;
    dialog.nMaxFile = capacity;
    dialog.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_EXPLORER;
    if unsafe { GetOpenFileNameW(&mut dialog) } == 0 {
        return if unsafe { CommDlgExtendedError() } == 0 {
            0
        } else {
            -1
        };
    }
    unsafe { slice::from_raw_parts(out, capacity as usize) }
        .iter()
        .position(|&c| c == 0)
        .map_or(-1, |n| n as i32)
}
