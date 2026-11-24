use crate::{Click, Profile};

#[derive(Default, Debug)]
pub struct Recorder {
    pub active: bool,
    pub button: String,
    pub clicks: Vec<Click>,
    down: Option<f64>,
    pending: Option<(u32, f64)>,
}
fn ms(n: f64) -> u32 {
    n.round().clamp(0., u32::MAX as f64) as u32
}
impl Recorder {
    pub fn start(&mut self, button: &str) {
        *self = Self {
            active: true,
            button: button.into(),
            ..Self::default()
        };
    }
    pub fn event(&mut self, now: f64, button: &str, down: bool, allowed: bool, injected: bool) {
        if !self.active || injected || button != self.button {
            return;
        }
        if down {
            if !allowed || self.down.is_some() {
                return;
            }
            if let Some((hold, up)) = self.pending.take() {
                self.clicks.push(Click {
                    hold_ms: hold,
                    gap_ms: ms(now - up),
                });
            }
            self.down = Some(now);
        } else if let Some(start) = self.down.take() {
            self.pending = Some((ms(now - start).max(1), now));
        }
    }
    pub fn count(&self) -> usize {
        self.clicks.len() + usize::from(self.pending.is_some())
    }
    pub fn stop(&mut self, now: f64) -> Profile {
        if let Some(start) = self.down.take() {
            self.pending = Some((ms(now - start).max(1), now));
        }
        if let Some((hold, _)) = self.pending.take() {
            let mut gaps: Vec<_> = self.clicks.iter().map(|c| c.gap_ms).collect();
            gaps.sort_unstable();
            let gap = if gaps.is_empty() {
                0
            } else {
                gaps[gaps.len() / 2]
            };
            self.clicks.push(Click {
                hold_ms: hold,
                gap_ms: gap,
            });
        }
        self.active = false;
        Profile {
            button: self.button.clone(),
            clicks: std::mem::take(&mut self.clicks),
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn records_hold_and_gap_ignoring_injected() {
        let mut r = Recorder::default();
        r.start("left");
        r.event(0., "left", true, true, true);
        r.event(10., "left", true, false, false);
        r.event(20., "left", true, true, false);
        r.event(25., "left", true, true, false);
        r.event(32., "left", false, true, false);
        r.event(60., "left", true, true, false);
        r.event(75., "left", false, true, false);
        let p = r.stop(80.);
        assert_eq!(
            p.clicks,
            vec![
                Click {
                    hold_ms: 12,
                    gap_ms: 28
                },
                Click {
                    hold_ms: 15,
                    gap_ms: 28
                }
            ]
        );
    }
    #[test]
    fn stop_completes_held_click() {
        let mut r = Recorder::default();
        r.start("right");
        r.event(5., "right", true, true, false);
        assert_eq!(
            r.stop(15.).clicks,
            vec![Click {
                hold_ms: 10,
                gap_ms: 0
            }]
        );
    }
}
