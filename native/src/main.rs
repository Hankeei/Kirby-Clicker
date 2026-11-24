#![windows_subsystem = "windows"]
mod ui;
use std::{path::PathBuf, time::Instant};

fn main() {
    if std::env::args().any(|a| a == "--verify-input") {
        let args: Vec<_> = std::env::args().collect();
        let result = (|| {
            let hwnd = args
                .get(2)
                .ok_or("Missing HWND")?
                .parse::<usize>()
                .map_err(|_| "Invalid HWND")?;
            let pid = args
                .get(3)
                .ok_or("Missing PID")?
                .parse::<u32>()
                .map_err(|_| "Invalid PID")?;
            let backend = args.get(4).ok_or("Missing backend")?;
            kirby_clicker::verification::run(hwnd, pid, backend)
        })();
        let ok = result.is_ok();
        let value = match result {
            Ok(v) => v,
            Err(e) => serde_json::json!({"ok":false,"error":e}),
        };
        if let Some(path) = std::env::var_os("KIRBYCLICKER_SELFTEST_OUT") {
            let _ = std::fs::write(path, serde_json::to_vec_pretty(&value).unwrap());
        }
        std::process::exit(if ok { 0 } else { 1 });
    }
    if std::env::args().any(|a| a == "--selftest") {
        let path = std::env::var_os("KIRBYCLICKER_SELFTEST_OUT")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("selftest-native.json"));
        let result = selftest();
        let ok = result.is_ok();
        let report = match result {
            Ok(v) => v,
            Err(e) => serde_json::json!({"ok":false,"error":e}),
        };
        let _ = std::fs::write(path, serde_json::to_vec_pretty(&report).unwrap());
        std::process::exit(if ok { 0 } else { 1 });
    }
    let start = Instant::now();
    let result = (|| -> Result<(), String> {
        let dir = kirby_clicker::data_directory().map_err(|e| e.to_string())?;
        let settings = kirby_clicker::settings::Settings::load(&dir.join("settings.json"));
        let icon = image::load_from_memory(include_bytes!("../../assets/icon.png"))
            .map_err(|e| e.to_string())?
            .into_rgba8();
        let viewport = eframe::egui::ViewportBuilder::default()
            .with_inner_size([560., 437.])
            .with_min_inner_size([440., 250.])
            .with_icon(eframe::egui::IconData {
                width: icon.width(),
                height: icon.height(),
                rgba: icon.into_raw(),
            });
        let options = eframe::NativeOptions {
            viewport,
            vsync: true,
            renderer: eframe::Renderer::Glow,
            ..Default::default()
        };
        eframe::run_native(
            "Kirby Clicker",
            options,
            Box::new(move |cc| Ok(Box::new(ui::Clicker::new(cc, dir, settings, start)))),
        )
        .map_err(|e| e.to_string())
    })();
    if let Err(error) = result {
        unsafe {
            windows_sys::Win32::UI::WindowsAndMessaging::MessageBoxW(
                std::ptr::null_mut(),
                kirby_clicker::platform::wide(&error).as_ptr(),
                kirby_clicker::platform::wide("Kirby Clicker could not start").as_ptr(),
                windows_sys::Win32::UI::WindowsAndMessaging::MB_ICONERROR,
            );
        }
    }
}

fn selftest() -> Result<serde_json::Value, String> {
    use kirby_clicker::*;
    use std::{sync::Arc, thread, time::Duration};
    let p = parse_profile("# ClickProfile v1 (GMK Clicker)\nbutton=right\n12 36\n18 29\n")?;
    if parse_profile(&profile_text(&p)?)? != p {
        return Err("Profile round-trip failed".into());
    }
    let c = engine::Control::new(
        settings::Settings::default(),
        binds::Binds::default(),
        || {},
    );
    {
        let mut s = c.lock();
        s.dry_run = true;
        s.profile = Some(Arc::new(p));
    }
    let worker = engine::Worker::start(c.clone());
    c.toggle();
    c.mouse("MOUSE1", true, 123456, true);
    if c.lock().clicking {
        return Err("Injected event triggered playback".into());
    }
    c.mouse("MOUSE1", true, 123456, false);
    thread::sleep(Duration::from_millis(230));
    c.mouse("MOUSE1", false, 123456, false);
    let sent = c.lock().sent;
    drop(worker);
    if sent < 3 {
        return Err("Dry-run playback did not run".into());
    }
    let events = c.lock().dry_events.clone();
    let max_drift = events
        .iter()
        .map(|e| (e.1 - e.0).abs())
        .fold(0_f64, f64::max);
    let max_hold_error = events
        .iter()
        .map(|e| (e.3 - e.2).abs())
        .fold(0_f64, f64::max);
    if events.len() < 3 || max_drift > 12. || max_hold_error > 12. {
        return Err(format!(
            "Dry-run timing failed: drift {max_drift:.2} ms, hold error {max_hold_error:.2} ms"
        ));
    }
    let gif = image::codecs::gif::GifDecoder::new(std::io::Cursor::new(include_bytes!(
        "../../assets/cat.gif"
    )))
    .map_err(|e| e.to_string())?;
    use image::AnimationDecoder;
    let frames = gif
        .into_frames()
        .collect_frames()
        .map_err(|e| e.to_string())?
        .len();
    if frames != 28 {
        return Err("Unexpected GIF frame count".into());
    }
    let audio = audio::Audio::start(data_directory().map_err(|e| e.to_string())?);
    audio.music(true, 0.05);
    let music = audio.status()?;
    thread::sleep(Duration::from_millis(230));
    let music_position = audio.position_ms();
    if music != "playing" || music_position == 0 {
        return Err(format!(
            "Music did not play: {music} at {music_position} ms"
        ));
    }
    audio.music(false, 0.05);
    if !audio.cue_checked(true) {
        return Err("ON cue failed".into());
    }
    thread::sleep(Duration::from_millis(170));
    if !audio.cue_checked(false) {
        return Err("OFF cue failed".into());
    }
    thread::sleep(Duration::from_millis(170));
    let exchange = storage::exchange(
        &parse_profile("# ClickProfile v1\nbutton=right\n12 36\n18 29")?,
        "Native profile 测试",
    )?;
    Ok(
        serde_json::json!({"ok":true,"version":env!("CARGO_PKG_VERSION"),"profile_compatibility":true,"injected_events_ignored":true,"dry_run_clicks":sent,"max_drift_ms":max_drift,"max_hold_error_ms":max_hold_error,"gif_frames":frames,"music_status":music,"music_position_ms":music_position,"toggle_sounds":true,"exchange_fixture":exchange,"exe_bytes":std::env::current_exe().ok().and_then(|p|std::fs::metadata(p).ok()).map(|m|m.len())}),
    )
}
