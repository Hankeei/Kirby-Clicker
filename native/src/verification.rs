//! Explicit integration probe, invoked only by tools/verify_native.py.
//! Real clicks are confined to that script's dedicated dummy window/process.
use crate::{
    Click, Profile,
    binds::Binds,
    engine::{Control, Worker},
    platform::{self, Action, Input},
    settings::Settings,
};
use std::{
    sync::{Arc, mpsc},
    thread,
    time::{Duration, Instant},
};
use windows_sys::Win32::{
    Foundation::HWND,
    UI::{Input::KeyboardAndMouse::*, WindowsAndMessaging::*},
};
fn wait(mut predicate: impl FnMut() -> bool) -> bool {
    let end = Instant::now() + Duration::from_secs(2);
    while Instant::now() < end {
        if predicate() {
            return true;
        }
        thread::sleep(Duration::from_millis(3));
    }
    false
}
fn tap(vk: u8) {
    unsafe {
        keybd_event(vk, 0, 0, 0);
        thread::sleep(Duration::from_millis(15));
        keybd_event(vk, 0, KEYEVENTF_KEYUP, 0);
    }
}
pub fn run(hwnd: usize, expected_pid: u32, backend: &str) -> Result<serde_json::Value, String> {
    let hwnd = hwnd as HWND;
    unsafe {
        let mut title = [0u16; 256];
        let n = GetWindowTextW(hwnd, title.as_mut_ptr(), 256);
        if platform::pid(hwnd) != expected_pid
            || String::from_utf16_lossy(&title[..n as usize])
                != "Kirby Clicker Native Verification Target"
        {
            return Err("Verification target identity mismatch".into());
        }
    }
    let mut binds = Binds::default();
    binds.scope = "restricted".into();
    binds.target = platform::exe_name(expected_pid);
    binds.trigger = "MOUSE4".into();
    let mut settings = Settings::default();
    settings.click_backend = backend.into();
    let c = Control::new(settings, binds, || {});
    {
        let mut s = c.lock();
        s.profile = Some(Arc::new(Profile {
            button: "left".into(),
            clicks: vec![
                Click {
                    hold_ms: 12,
                    gap_ms: 38,
                },
                Click {
                    hold_ms: 18,
                    gap_ms: 32,
                },
                Click {
                    hold_ms: 10,
                    gap_ms: 40,
                },
            ],
        }));
    }
    let (tx, rx) = mpsc::channel();
    let _input = Input::start(c.clone(), tx)?;
    let worker = Worker::start(c.clone());
    tap(0x78);
    let mut hotkey = false;
    let mut warnings = vec![];
    let end = Instant::now() + Duration::from_secs(1);
    while Instant::now() < end {
        if let Ok(a) = rx.recv_timeout(Duration::from_millis(20)) {
            match a {
                Action::Hotkey(a) if a == "toggle" => {
                    hotkey = true;
                    break;
                }
                Action::Warning(w) => warnings.push(w),
                _ => {}
            }
        }
    }
    if !hotkey {
        return Err(format!("F9 not delivered: {warnings:?}"));
    }
    c.toggle();
    // Injected input must not feed back into the hold trigger or recorder.
    if !platform::send_mouse("x1", true) || !platform::send_mouse("x1", false) {
        return Err("Injected input was rejected".into());
    }
    thread::sleep(Duration::from_millis(20));
    if c.lock().clicking {
        return Err("Injected input triggered playback".into());
    }
    // A physical-device harness is not available: exercise the same intake
    // method called by the hook, then verify actual output at the dummy window.
    c.mouse("MOUSE4", true, expected_pid, false);
    if !wait(|| c.lock().sent >= 3) {
        return Err(format!("No playback: {}", c.lock().error));
    }
    c.mouse("MOUSE4", false, expected_pid, false);
    let count = c.lock().sent;
    thread::sleep(Duration::from_millis(80));
    if c.lock().sent != count {
        return Err("Playback continued after release".into());
    }
    // Recording events remain separate from generated clicks.
    c.start_record()?;
    c.mouse("MOUSE1", true, expected_pid, false);
    thread::sleep(Duration::from_millis(15));
    c.mouse("MOUSE1", false, expected_pid, false);
    let p = c.stop_record();
    if p.clicks.len() != 1 {
        return Err("Recorder did not capture physical intake".into());
    }
    {
        let mut s = c.lock();
        s.settings.active_tab = 1;
        s.settings.auto_min_cps = 40.;
        s.settings.auto_max_cps = 40.;
        s.settings.auto_method = "static".into();
        s.error.clear();
    }
    c.toggle();
    c.mouse("MOUSE4", true, expected_pid, false);
    if !wait(|| c.lock().sent >= 3) {
        return Err("Auto playback failed".into());
    }
    c.mouse("MOUSE4", false, expected_pid, false);
    let auto_count = c.lock().sent;
    drop(worker);
    Ok(
        serde_json::json!({"ok":true,"backend":backend,"f9":hotkey,"profile_clicks":count,"auto_clicks":auto_count,"recorded_clicks":p.clicks.len(),"stop_on_release":true,"physical_device_tested":false,"warnings":warnings}),
    )
}
