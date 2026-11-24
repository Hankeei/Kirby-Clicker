//! One sleeping playback worker; physical release wakes its condition variable.
use crate::{
    Profile,
    binds::Binds,
    platform::{self, Delivery, Scope},
    recorder::Recorder,
    settings::Settings,
};
use rand::Rng;
use std::{
    collections::VecDeque,
    sync::{Arc, Condvar, Mutex, MutexGuard},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub struct State {
    pub settings: Settings,
    pub binds: Binds,
    pub profile: Option<Arc<Profile>>,
    pub recorder: Recorder,
    pub record_button: String,
    pub record_target: Option<u32>,
    pub dry_run: bool,
    pub armed: bool,
    pub trigger_down: bool,
    pub clicking: bool,
    pub epoch: u64,
    pub shutdown: bool,
    pub sent: u64,
    pub skipped: u64,
    pub recent: VecDeque<f64>,
    pub dry_events: VecDeque<(f64, f64, f64, f64)>,
    pub error: String,
}
impl State {
    pub fn new(settings: Settings, binds: Binds) -> Self {
        Self {
            settings,
            binds,
            profile: None,
            recorder: Recorder::default(),
            record_button: "left".into(),
            record_target: None,
            dry_run: false,
            armed: false,
            trigger_down: false,
            clicking: false,
            epoch: 0,
            shutdown: false,
            sent: 0,
            skipped: 0,
            recent: VecDeque::new(),
            dry_events: VecDeque::new(),
            error: String::new(),
        }
    }
    pub fn cancel(&mut self) {
        self.clicking = false;
        self.epoch = self.epoch.wrapping_add(1);
    }
}
pub struct Control {
    state: Mutex<State>,
    cv: Condvar,
    start: Instant,
    wake: Arc<dyn Fn() + Send + Sync>,
}
impl Control {
    pub fn new(
        settings: Settings,
        binds: Binds,
        wake: impl Fn() + Send + Sync + 'static,
    ) -> Arc<Self> {
        Arc::new(Self {
            state: Mutex::new(State::new(settings, binds)),
            cv: Condvar::new(),
            start: Instant::now(),
            wake: Arc::new(wake),
        })
    }
    pub fn lock(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(|p| p.into_inner())
    }
    pub fn now_ms(&self) -> f64 {
        self.start.elapsed().as_secs_f64() * 1000.
    }
    pub fn repaint(&self) {
        (self.wake)();
    }
    pub fn notify(&self) {
        self.cv.notify_all();
        self.repaint();
    }
    pub fn wake_worker(&self) {
        self.cv.notify_all();
    }
    pub fn toggle(&self) -> bool {
        let mut s = self.lock();
        if s.recorder.active {
            return s.armed;
        }
        s.armed = !s.armed;
        if !s.armed {
            s.cancel();
        }
        let armed = s.armed;
        drop(s);
        self.notify();
        armed
    }
    pub fn disarm(&self) {
        let mut s = self.lock();
        s.armed = false;
        s.cancel();
        drop(s);
        self.notify();
    }
    pub fn mouse(&self, name: &str, down: bool, owner: u32, injected: bool) {
        if injected {
            return;
        }
        let mut s = self.lock();
        let button = match name {
            "MOUSE1" => "left",
            "MOUSE2" => "right",
            "MOUSE3" => "middle",
            _ => "",
        };
        let allowed = owner != 0
            && owner != platform::own_pid()
            && s.record_target.is_none_or(|p| p == owner);
        s.recorder
            .event(self.now_ms(), button, down, allowed, false);
        if name == s.binds.trigger {
            if down && !s.trigger_down {
                s.trigger_down = true;
                if s.armed && !s.recorder.active && owner != platform::own_pid() {
                    s.cancel();
                    s.clicking = true;
                    s.sent = 0;
                    s.skipped = 0;
                    s.recent.clear();
                    s.dry_events.clear();
                    s.error.clear();
                }
            } else if !down && s.trigger_down {
                s.trigger_down = false;
                s.cancel();
            }
        }
        drop(s);
        self.notify();
    }
    pub fn start_record(&self) -> Result<(), String> {
        let binds = self.lock().binds.clone();
        let scope = Scope::new(&binds)?;
        let mut s = self.lock();
        s.armed = false;
        s.cancel();
        s.record_target = scope.target.map(|t| t.pid);
        let b = s.record_button.clone();
        s.recorder.start(&b);
        drop(s);
        self.notify();
        Ok(())
    }
    pub fn stop_record(&self) -> Profile {
        let mut s = self.lock();
        let p = s.recorder.stop(self.now_ms());
        s.record_target = None;
        drop(s);
        self.notify();
        p
    }
    pub fn stop(&self) {
        let mut s = self.lock();
        s.shutdown = true;
        s.cancel();
        drop(s);
        self.notify();
    }
    fn live(&self, epoch: u64) -> bool {
        let s = self.lock();
        !s.shutdown && s.clicking && s.epoch == epoch
    }
    fn abort(&self, epoch: u64, error: String) {
        let mut s = self.lock();
        if s.epoch == epoch {
            s.error = error;
            s.cancel();
        }
        drop(s);
        self.notify();
    }
    fn wait(&self, until: Instant, epoch: u64, scope: &mut Scope, dry: bool) -> bool {
        loop {
            let s = self.lock();
            if s.shutdown || !s.clicking || s.epoch != epoch {
                return false;
            }
            let now = Instant::now();
            if now >= until {
                return true;
            }
            let timeout = (until - now).min(Duration::from_millis(5));
            let (guard, _) = self
                .cv
                .wait_timeout(s, timeout)
                .unwrap_or_else(|p| p.into_inner());
            drop(guard);
            if !dry {
                if let Err(e) = scope.check_lifetime() {
                    self.abort(epoch, e);
                    return false;
                }
            }
        }
    }
}
pub struct Worker {
    control: Arc<Control>,
    join: Option<JoinHandle<()>>,
}
impl Worker {
    pub fn start(control: Arc<Control>) -> Self {
        let c = control.clone();
        let join = thread::spawn(move || run(c));
        Self {
            control,
            join: Some(join),
        }
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        self.control.stop();
        if let Some(j) = self.join.take() {
            let _ = j.join();
        }
    }
}
struct TimerPeriod;
impl TimerPeriod {
    fn new() -> Self {
        unsafe {
            windows_sys::Win32::Media::timeBeginPeriod(1);
        }
        Self
    }
}
impl Drop for TimerPeriod {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Media::timeEndPeriod(1);
        }
    }
}
fn run(c: Arc<Control>) {
    let mut rng = rand::rng();
    loop {
        let mut s = c.lock();
        while !s.shutdown && !s.clicking {
            s = c.cv.wait(s).unwrap_or_else(|p| p.into_inner());
        }
        if s.shutdown {
            return;
        }
        let epoch = s.epoch;
        let settings = s.settings.clone();
        let binds = s.binds.clone();
        let profile = s.profile.clone();
        let auto = settings.active_tab == 1;
        let dry = s.dry_run && !auto;
        drop(s);
        let mut scope = if dry {
            Scope {
                target: None,
                had_focus: false,
            }
        } else {
            match Scope::new(&binds) {
                Ok(t) => t,
                Err(e) => {
                    c.abort(epoch, e);
                    continue;
                }
            }
        };
        if !auto && profile.as_ref().is_none_or(|p| p.clicks.is_empty()) {
            c.abort(epoch, "Load a profile before playback".into());
            continue;
        }
        let button = if auto {
            settings.auto_button.as_str()
        } else {
            &profile.as_ref().unwrap().button
        };
        let mut output = Delivery::new(button, settings.click_backend == "background", dry);
        let _timer = TimerPeriod::new();
        let mut index = 0;
        let started = Instant::now();
        let mut deadline = started;
        while c.live(epoch) {
            let (hold, interval) = if auto {
                let gap = crate::sample_gap(
                    &mut rng,
                    settings.auto_min_cps,
                    settings.auto_max_cps,
                    &settings.auto_method,
                    settings.auto_sigma,
                );
                let low = (gap * 0.1).max(3.);
                let high = (gap * 0.45).max(low).min(120.);
                (rng.random_range(low..=high).min(gap * 0.9), gap)
            } else {
                let p = profile.as_ref().unwrap();
                let click = &p.clicks[index % p.clicks.len()];
                index += 1;
                (
                    click.hold_ms as f64,
                    (click.hold_ms as f64 + click.gap_ms as f64).max(1.),
                )
            };
            if !c.wait(deadline, epoch, &mut scope, dry) {
                break;
            }
            // Synchronize the final press with disarm/release. Injected events
            // return before taking this lock in the hook callback.
            let mut s = c.lock();
            if s.epoch != epoch || !s.clicking || s.shutdown {
                break;
            }
            let down_at = Instant::now();
            let pressed = output.press(&scope);
            match &pressed {
                Ok(()) => {
                    s.sent += 1;
                    s.recent.push_back(interval);
                    if s.recent.len() > 24 {
                        s.recent.pop_front();
                    }
                }
                Err(e) => {
                    s.skipped += 1;
                    s.error = e.clone();
                }
            }
            drop(s);
            c.repaint();
            if pressed.is_ok() {
                let completed = c.wait(
                    down_at + Duration::from_secs_f64(hold / 1000.),
                    epoch,
                    &mut scope,
                    dry,
                );
                if let Err(e) = output.release() {
                    c.abort(epoch, e);
                    break;
                }
                if dry && completed {
                    let mut s = c.lock();
                    if s.epoch == epoch {
                        s.dry_events.push_back((
                            (deadline - started).as_secs_f64() * 1000.,
                            (down_at - started).as_secs_f64() * 1000.,
                            hold,
                            down_at.elapsed().as_secs_f64() * 1000.,
                        ));
                        if s.dry_events.len() > 256 {
                            s.dry_events.pop_front();
                        }
                    }
                }
            }
            deadline += Duration::from_secs_f64(interval / 1000.);
            // Never emit a burst of catch-up clicks after the machine stalls.
            if deadline < Instant::now() {
                deadline = Instant::now();
            }
        }
        if let Err(e) = output.release() {
            c.abort(epoch, e);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn injected_events_cannot_trigger_and_release_interrupts_hold() {
        let mut settings = Settings::default();
        settings.active_tab = 0;
        let c = Control::new(settings, Binds::default(), || {});
        {
            let mut s = c.lock();
            s.dry_run = true;
            s.profile = Some(Arc::new(Profile {
                button: "left".into(),
                clicks: vec![crate::Click {
                    hold_ms: 5000,
                    gap_ms: 0,
                }],
            }));
        }
        let _w = Worker::start(c.clone());
        c.toggle();
        c.mouse("MOUSE1", true, 999, true);
        assert!(!c.lock().clicking);
        c.mouse("MOUSE1", true, 999, false);
        let deadline = Instant::now() + Duration::from_secs(1);
        while c.lock().sent == 0 && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(1));
        }
        assert_eq!(c.lock().sent, 1);
        let at = Instant::now();
        c.mouse("MOUSE1", false, 999, false);
        drop(_w);
        assert!(at.elapsed() < Duration::from_millis(200));
        assert!(!c.lock().clicking);
    }
    #[test]
    fn own_window_and_recording_cannot_start_playback() {
        let c = Control::new(Settings::default(), Binds::default(), || {});
        c.toggle();
        c.mouse("MOUSE1", true, platform::own_pid(), false);
        assert!(!c.lock().clicking);
        c.mouse("MOUSE1", false, 0, false);
        c.start_record().unwrap();
        c.toggle();
        assert!(!c.lock().armed);
    }
    #[test]
    fn release_without_press_duplicate_down_and_wrong_button_are_ignored() {
        let c = Control::new(Settings::default(), Binds::default(), || {});
        c.toggle();
        c.mouse("MOUSE1", false, 999, false);
        assert!(!c.lock().clicking);
        c.mouse("MOUSE2", true, 999, false);
        assert!(!c.lock().clicking);
        c.mouse("MOUSE1", true, 999, false);
        let epoch = c.lock().epoch;
        c.mouse("MOUSE1", true, 999, false);
        assert_eq!(c.lock().epoch, epoch);
        c.mouse("MOUSE1", false, 0, false);
        assert!(!c.lock().clicking);
    }
    #[test]
    fn arming_while_trigger_held_requires_a_fresh_press() {
        let c = Control::new(Settings::default(), Binds::default(), || {});
        c.mouse("MOUSE1", true, 999, false);
        c.toggle();
        assert!(!c.lock().clicking);
        c.mouse("MOUSE1", true, 999, false);
        assert!(!c.lock().clicking);
        c.mouse("MOUSE1", false, 999, false);
        c.mouse("MOUSE1", true, 999, false);
        assert!(c.lock().clicking);
    }
}
