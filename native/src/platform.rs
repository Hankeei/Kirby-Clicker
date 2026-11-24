//! Win32 boundary. Pointer lifetimes and callback ownership stay in this module.
use crate::{
    binds::{ACTIONS, Binds, key_vk},
    engine::Control,
};
use std::{
    ptr::null_mut,
    sync::{Arc, mpsc},
    thread::{self, JoinHandle},
};
use windows_sys::Win32::{
    Foundation::*,
    System::{LibraryLoader::GetModuleHandleW, Threading::*},
    UI::{Input::KeyboardAndMouse::*, WindowsAndMessaging::*},
};

pub fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}
pub fn replace_file(source: &std::path::Path, target: &std::path::Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH, MoveFileExW,
    };
    let from: Vec<_> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let to: Vec<_> = target.as_os_str().encode_wide().chain(Some(0)).collect();
    if unsafe {
        MoveFileExW(
            from.as_ptr(),
            to.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    } == 0
    {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}
pub fn utc_now() -> String {
    unsafe {
        let mut t = std::mem::zeroed();
        windows_sys::Win32::System::SystemInformation::GetSystemTime(&mut t);
        format!(
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
            t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond
        )
    }
}
/// Resolve a process ID at the Win32 boundary.
///
/// # Safety
/// `hwnd` must be a window handle obtained from Windows, never a Rust pointer.
/// Windows validates null or stale handles and returns zero for them.
pub unsafe fn pid(hwnd: HWND) -> u32 {
    unsafe {
        let mut p = 0;
        GetWindowThreadProcessId(hwnd, &mut p);
        p
    }
}
pub fn own_pid() -> u32 {
    unsafe { GetCurrentProcessId() }
}
pub fn exe_name(id: u32) -> String {
    unsafe {
        let h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, id);
        if h.is_null() {
            return String::new();
        }
        let mut b = vec![0u16; 32768];
        let mut len = b.len() as u32;
        let ok = QueryFullProcessImageNameW(h, 0, b.as_mut_ptr(), &mut len);
        CloseHandle(h);
        if ok == 0 {
            return String::new();
        }
        std::path::Path::new(&String::from_utf16_lossy(&b[..len as usize]))
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned()
    }
}
#[derive(Clone, Debug)]
pub struct Window {
    pub hwnd: usize,
    pub pid: u32,
    pub exe: String,
    pub title: String,
}
pub fn windows() -> Vec<Window> {
    unsafe extern "system" fn collect(hwnd: HWND, data: isize) -> i32 {
        unsafe {
            if IsWindowVisible(hwnd) == 0 || GetWindowTextLengthW(hwnd) == 0 {
                return 1;
            }
            let p = pid(hwnd);
            if p == own_pid() {
                return 1;
            }
            let mut text = vec![0u16; GetWindowTextLengthW(hwnd) as usize + 1];
            let n = GetWindowTextW(hwnd, text.as_mut_ptr(), text.len() as i32);
            let exe = exe_name(p);
            if !exe.is_empty() {
                (*(data as *mut Vec<Window>)).push(Window {
                    hwnd: hwnd as usize,
                    pid: p,
                    exe,
                    title: String::from_utf16_lossy(&text[..n as usize]),
                });
            }
            1
        }
    }
    let mut result: Vec<Window> = Vec::new();
    unsafe {
        EnumWindows(Some(collect), &mut result as *mut _ as isize);
    }
    result.sort_by_key(|w| w.exe.to_lowercase());
    result
}
pub fn cursor() -> POINT {
    unsafe {
        let mut p = POINT { x: 0, y: 0 };
        GetCursorPos(&mut p);
        p
    }
}
pub fn cursor_owner() -> u32 {
    unsafe { pid(GetAncestor(WindowFromPoint(cursor()), GA_ROOT)) }
}
#[derive(Clone, Debug)]
pub struct Scope {
    pub target: Option<Window>,
    pub had_focus: bool,
}
impl Scope {
    pub fn new(binds: &Binds) -> Result<Self, String> {
        let target = if binds.scope == "restricted" {
            Some(
                windows()
                    .into_iter()
                    .find(|w| w.exe.eq_ignore_ascii_case(&binds.target))
                    .ok_or("Selected app is not running")?,
            )
        } else {
            None
        };
        let had_focus = target
            .as_ref()
            .is_some_and(|t| unsafe { pid(GetForegroundWindow()) == t.pid });
        Ok(Self { target, had_focus })
    }
    pub fn check_lifetime(&mut self) -> Result<(), String> {
        if let Some(t) = &self.target {
            unsafe {
                if IsWindow(t.hwnd as HWND) == 0 || pid(t.hwnd as HWND) != t.pid {
                    return Err("Target window closed".into());
                }
                if pid(GetForegroundWindow()) == t.pid {
                    self.had_focus = true;
                } else if self.had_focus {
                    return Err("Target lost foreground focus".into());
                }
            }
        }
        Ok(())
    }
    pub fn resolve(&self) -> Result<HWND, String> {
        unsafe {
            let hwnd = WindowFromPoint(cursor());
            if hwnd.is_null() {
                return Err("No window under cursor".into());
            }
            let owner = pid(GetAncestor(hwnd, GA_ROOT));
            if owner == own_pid() || pid(hwnd) == own_pid() {
                return Err("Cursor is over Kirby Clicker".into());
            }
            if self
                .target
                .as_ref()
                .is_some_and(|t| t.pid != owner || t.pid != pid(hwnd))
            {
                return Err("Cursor is outside the selected app".into());
            }
            Ok(hwnd)
        }
    }
}
pub fn send_mouse(button: &str, down: bool) -> bool {
    unsafe {
        let flags = match (button, down) {
            ("x1" | "x2", true) => MOUSEEVENTF_XDOWN,
            ("x1" | "x2", false) => MOUSEEVENTF_XUP,
            ("right", true) => MOUSEEVENTF_RIGHTDOWN,
            ("right", false) => MOUSEEVENTF_RIGHTUP,
            ("middle", true) => MOUSEEVENTF_MIDDLEDOWN,
            ("middle", false) => MOUSEEVENTF_MIDDLEUP,
            (_, true) => MOUSEEVENTF_LEFTDOWN,
            (_, false) => MOUSEEVENTF_LEFTUP,
        };
        let mut input: INPUT = std::mem::zeroed();
        input.r#type = INPUT_MOUSE;
        input.Anonymous.mi.dwFlags = flags;
        if button == "x1" {
            input.Anonymous.mi.mouseData = 1;
        } else if button == "x2" {
            input.Anonymous.mi.mouseData = 2;
        }
        SendInput(1, &input, std::mem::size_of::<INPUT>() as i32) == 1
    }
}
pub struct Delivery {
    pub button: String,
    background: bool,
    hwnd: usize,
    point: POINT,
    held: bool,
    dry: bool,
}
impl Delivery {
    pub fn new(button: &str, background: bool, dry: bool) -> Self {
        Self {
            button: button.into(),
            background,
            hwnd: 0,
            point: POINT { x: 0, y: 0 },
            held: false,
            dry,
        }
    }
    pub fn press(&mut self, scope: &Scope) -> Result<(), String> {
        self.release()?;
        if self.dry {
            self.held = true;
            return Ok(());
        }
        let hwnd = scope.resolve()?;
        if self.background {
            self.hwnd = hwnd as usize;
            self.point = cursor();
            unsafe {
                windows_sys::Win32::Graphics::Gdi::ScreenToClient(hwnd, &mut self.point);
            }
            if !self.post(true) {
                return Err("Background click rejected".into());
            }
        } else if !send_mouse(&self.button, true) {
            return Err("SendInput rejected (check application privileges)".into());
        }
        self.held = true;
        Ok(())
    }
    fn post(&self, down: bool) -> bool {
        unsafe {
            let (msg, mask) = match (self.button.as_str(), down) {
                ("right", true) => (WM_RBUTTONDOWN, 2),
                ("right", false) => (WM_RBUTTONUP, 0),
                ("middle", true) => (WM_MBUTTONDOWN, 16),
                ("middle", false) => (WM_MBUTTONUP, 0),
                (_, true) => (WM_LBUTTONDOWN, 1),
                (_, false) => (WM_LBUTTONUP, 0),
            };
            let point = (self.point.x as u16 as u32) | ((self.point.y as u16 as u32) << 16);
            PostMessageW(self.hwnd as HWND, msg, mask, point as isize) != 0
        }
    }
    pub fn release(&mut self) -> Result<(), String> {
        if !self.held {
            return Ok(());
        }
        self.held = false;
        if self.dry {
            return Ok(());
        }
        let ok = if self.background {
            self.post(false)
        } else {
            send_mouse(&self.button, false)
        };
        if ok {
            Ok(())
        } else {
            Err("Mouse release failed; check application privileges".into())
        }
    }
}
impl Drop for Delivery {
    fn drop(&mut self) {
        let _ = self.release();
    }
}

#[derive(Clone, Debug)]
pub enum Action {
    Hotkey(String),
    Warning(String),
}
struct HookContext {
    control: Arc<Control>,
}
thread_local! {static HOOK:std::cell::RefCell<Option<HookContext>>=const{std::cell::RefCell::new(None)};}
unsafe extern "system" fn mouse_hook(code: i32, w: usize, l: isize) -> isize {
    if code == HC_ACTION as i32 {
        unsafe {
            let data = &*(l as *const MSLLHOOKSTRUCT);
            // Return before locking: SendInput can synchronously wait for this callback.
            if data.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED) == 0 {
                let (name, down) = match w as u32 {
                    WM_LBUTTONDOWN => ("MOUSE1", true),
                    WM_LBUTTONUP => ("MOUSE1", false),
                    WM_RBUTTONDOWN => ("MOUSE2", true),
                    WM_RBUTTONUP => ("MOUSE2", false),
                    WM_MBUTTONDOWN => ("MOUSE3", true),
                    WM_MBUTTONUP => ("MOUSE3", false),
                    WM_XBUTTONDOWN | WM_XBUTTONUP => (
                        if data.mouseData >> 16 == 1 {
                            "MOUSE4"
                        } else {
                            "MOUSE5"
                        },
                        w as u32 == WM_XBUTTONDOWN,
                    ),
                    _ => return CallNextHookEx(null_mut(), code, w, l),
                };
                let owner = pid(GetAncestor(WindowFromPoint(data.pt), GA_ROOT));
                HOOK.with(|ctx| {
                    if let Some(ctx) = ctx.borrow().as_ref() {
                        ctx.control.mouse(name, down, owner, false);
                    }
                });
            }
        }
    }
    unsafe { CallNextHookEx(null_mut(), code, w, l) }
}
fn register(binds: &Binds, tx: &mpsc::Sender<Action>) -> Vec<i32> {
    let mut ids = Vec::new();
    for (i, action) in ACTIONS.iter().enumerate() {
        let id = 100 + i as i32;
        let vk = key_vk(&binds.keys[*action]).unwrap_or(0);
        unsafe {
            if RegisterHotKey(null_mut(), id, MOD_NOREPEAT, vk) != 0 {
                ids.push(id);
            } else if RegisterHotKey(null_mut(), id, MOD_NOREPEAT | MOD_CONTROL, vk) != 0 {
                ids.push(id);
                let _ = tx.send(Action::Warning(format!(
                    "{} is busy; use Ctrl+{} for {action}",
                    binds.keys[*action], binds.keys[*action]
                )));
            } else {
                let _ = tx.send(Action::Warning(format!(
                    "Could not register {} ({action}); change it in Settings",
                    binds.keys[*action]
                )));
            }
        }
    }
    ids
}
pub struct Input {
    thread_id: u32,
    join: Option<JoinHandle<()>>,
}
impl Input {
    pub fn start(control: Arc<Control>, tx: mpsc::Sender<Action>) -> Result<Self, String> {
        let (ready, rx) = mpsc::sync_channel(1);
        let join = thread::spawn(move || unsafe {
            let mut msg: MSG = std::mem::zeroed();
            PeekMessageW(&mut msg, null_mut(), 0, 0, PM_NOREMOVE);
            let id = GetCurrentThreadId();
            HOOK.with(|h| {
                *h.borrow_mut() = Some(HookContext {
                    control: control.clone(),
                })
            });
            let hook = SetWindowsHookExW(
                WH_MOUSE_LL,
                Some(mouse_hook),
                GetModuleHandleW(std::ptr::null()),
                0,
            );
            if hook.is_null() {
                let _ = ready.send(Err(format!(
                    "Mouse hook failed: {}",
                    std::io::Error::last_os_error()
                )));
                return;
            }
            let mut ids = register(&control.lock().binds, &tx);
            let _ = ready.send(Ok(id));
            while GetMessageW(&mut msg, null_mut(), 0, 0) > 0 {
                if msg.message == WM_HOTKEY {
                    let i = msg.wParam.saturating_sub(100);
                    if i < ACTIONS.len() {
                        let _ = tx.send(Action::Hotkey(ACTIONS[i].into()));
                        control.repaint();
                    }
                } else if msg.message == WM_APP + 1 {
                    for id in ids.drain(..) {
                        UnregisterHotKey(null_mut(), id);
                    }
                    ids = register(&control.lock().binds, &tx);
                } else {
                    TranslateMessage(&msg);
                    DispatchMessageW(&msg);
                }
            }
            for id in ids {
                UnregisterHotKey(null_mut(), id);
            }
            UnhookWindowsHookEx(hook);
            HOOK.with(|h| *h.borrow_mut() = None);
        });
        match rx.recv_timeout(std::time::Duration::from_secs(3)) {
            Ok(Ok(id)) => Ok(Self {
                thread_id: id,
                join: Some(join),
            }),
            Ok(Err(e)) => {
                let _ = join.join();
                Err(e)
            }
            Err(e) => Err(format!("Input startup timed out: {e}")),
        }
    }
    pub fn rebind(&self) {
        unsafe {
            PostThreadMessageW(self.thread_id, WM_APP + 1, 0, 0);
        }
    }
}
impl Drop for Input {
    fn drop(&mut self) {
        unsafe {
            PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0);
        }
        if let Some(j) = self.join.take() {
            let _ = j.join();
        }
    }
}

pub fn open(path: &std::path::Path) {
    unsafe {
        windows_sys::Win32::UI::Shell::ShellExecuteW(
            null_mut(),
            wide("open").as_ptr(),
            wide(&path.to_string_lossy()).as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            SW_SHOWNORMAL,
        );
    }
}
pub fn compact_style(compact: bool) {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static MAIN: AtomicUsize = AtomicUsize::new(0);
    unsafe extern "system" fn find(hwnd: HWND, param: isize) -> i32 {
        unsafe {
            let mut title = [0u16; 64];
            let n = GetWindowTextW(hwnd, title.as_mut_ptr(), 64);
            if pid(hwnd) == own_pid()
                && String::from_utf16_lossy(&title[..n as usize]) == "Kirby Clicker"
            {
                *(param as *mut HWND) = hwnd;
                return 0;
            }
            1
        }
    }
    unsafe {
        let mut hwnd = MAIN.load(Ordering::Relaxed) as HWND;
        if hwnd.is_null() || IsWindow(hwnd) == 0 {
            hwnd = null_mut();
            EnumWindows(Some(find), &mut hwnd as *mut HWND as isize);
            MAIN.store(hwnd as usize, Ordering::Relaxed);
        }
        if !hwnd.is_null() {
            let previous = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
            let mut style = previous;
            if compact {
                style |= (WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) as isize;
                style &= !(WS_EX_APPWINDOW as isize);
            } else {
                style &= !((WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) as isize);
                style |= WS_EX_APPWINDOW as isize;
            }
            if style != previous {
                SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style);
            }
        }
    }
}
pub fn file_dialog(save: bool, exchange: bool) -> Option<std::path::PathBuf> {
    unsafe {
        use windows_sys::Win32::UI::Controls::Dialogs::*;
        let mut name = vec![0u16; 32768];
        let filter = wide(if exchange {
            "Kirby profiles\0*.rcprofile.json;*.json;*.txt\0All files\0*.*\0"
        } else {
            "ClickProfile\0*.txt\0All files\0*.*\0"
        });
        let mut dialog: OPENFILENAMEW = std::mem::zeroed();
        dialog.lStructSize = std::mem::size_of::<OPENFILENAMEW>() as u32;
        dialog.lpstrFile = name.as_mut_ptr();
        dialog.nMaxFile = name.len() as u32;
        dialog.lpstrFilter = filter.as_ptr();
        dialog.lpstrDefExt = if exchange {
            windows_sys::core::w!("rcprofile.json")
        } else {
            windows_sys::core::w!("txt")
        };
        dialog.Flags = OFN_EXPLORER
            | OFN_NOCHANGEDIR
            | if save {
                OFN_OVERWRITEPROMPT
            } else {
                OFN_FILEMUSTEXIST
            };
        let ok = if save {
            GetSaveFileNameW(&mut dialog)
        } else {
            GetOpenFileNameW(&mut dialog)
        };
        if ok == 0 {
            None
        } else {
            Some(
                String::from_utf16_lossy(&name[..name.iter().position(|c| *c == 0).unwrap_or(0)])
                    .into(),
            )
        }
    }
}
