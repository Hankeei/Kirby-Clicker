use std::collections::{BTreeMap, HashSet};

pub const ACTIONS: [&str; 5] = ["record", "toggle", "quit", "rebind", "selector"];
#[derive(Clone, Debug)]
pub struct Binds {
    pub keys: BTreeMap<String, String>,
    pub trigger: String,
    pub scope: String,
    pub target: String,
    pub extra: BTreeMap<String, String>,
}
impl Default for Binds {
    fn default() -> Self {
        Self {
            keys: [
                ("record", "F8"),
                ("toggle", "F9"),
                ("quit", "F12"),
                ("rebind", "INSERT"),
                ("selector", "F10"),
            ]
            .into_iter()
            .map(|(k, v)| (k.into(), v.into()))
            .collect(),
            trigger: "MOUSE1".into(),
            scope: "anywhere".into(),
            target: String::new(),
            extra: BTreeMap::new(),
        }
    }
}
pub fn canonical(key: &str) -> String {
    let key = key.trim().to_uppercase();
    match key.as_str() {
        "ESCAPE" => "ESC".into(),
        "RETURN" => "ENTER".into(),
        "DEL" => "DELETE".into(),
        "INS" => "INSERT".into(),
        "PGUP" => "PAGEUP".into(),
        "PGDN" => "PAGEDOWN".into(),
        "CTRL" => "LCTRL".into(),
        "SHIFT" => "LSHIFT".into(),
        "ALT" => "LALT".into(),
        "LMB" | "LEFTMOUSE" | "MOUSELEFT" => "MOUSE1".into(),
        "RMB" | "RIGHTMOUSE" | "MOUSERIGHT" => "MOUSE2".into(),
        "MMB" | "MOUSEMIDDLE" => "MOUSE3".into(),
        _ if key.starts_with("NUM") && key.len() == 4 && key.as_bytes()[3].is_ascii_digit() => {
            format!("NUMPAD{}", &key[3..])
        }
        _ => key,
    }
}
pub fn key_vk(key: &str) -> Option<u32> {
    let key = canonical(key);
    if key.len() == 1 && key.as_bytes()[0].is_ascii_alphanumeric() {
        return Some(key.as_bytes()[0] as u32);
    }
    if let Some(n) = key
        .strip_prefix('F')
        .and_then(|s| s.parse::<u32>().ok())
        .filter(|n| (1..=24).contains(n))
    {
        return Some(0x6f + n);
    }
    if let Some(n) = key
        .strip_prefix("NUMPAD")
        .and_then(|s| s.parse::<u32>().ok())
        .filter(|n| *n <= 9)
    {
        return Some(0x60 + n);
    }
    Some(match key.as_str() {
        "SPACE" => 0x20,
        "TAB" => 9,
        "ENTER" => 13,
        "ESC" => 27,
        "BACKSPACE" => 8,
        "INSERT" => 0x2d,
        "DELETE" => 0x2e,
        "HOME" => 0x24,
        "END" => 0x23,
        "PAGEUP" => 0x21,
        "PAGEDOWN" => 0x22,
        "UP" => 0x26,
        "DOWN" => 0x28,
        "LEFT" => 0x25,
        "RIGHT" => 0x27,
        "LSHIFT" => 0xa0,
        "RSHIFT" => 0xa1,
        "LCTRL" => 0xa2,
        "RCTRL" => 0xa3,
        "LALT" => 0xa4,
        "RALT" => 0xa5,
        _ => return None,
    })
}
pub fn mouse_key(key: &str) -> bool {
    ["MOUSE1", "MOUSE2", "MOUSE3", "MOUSE4", "MOUSE5"].contains(&key)
}
impl Binds {
    pub fn parse(text: &str) -> Result<Self, String> {
        let mut b = Self::default();
        let mut scope = false;
        let mut trigger = false;
        let mut hold = None;
        for line in text.trim_start_matches('\u{feff}').lines().map(str::trim) {
            if line.starts_with('#') {
                continue;
            }
            if let Some((k, v)) = line.split_once('=') {
                let k = k.trim().to_lowercase();
                let v = v.trim();
                match k.as_str() {
                    "target" => b.target = v.into(),
                    "scope" => {
                        b.scope = v.to_lowercase();
                        scope = true;
                    }
                    "trigger" => {
                        b.trigger = canonical(v);
                        trigger = true;
                    }
                    "hold" => hold = Some(canonical(v)),
                    _ if ACTIONS.contains(&k.as_str()) => {
                        b.keys.insert(k, canonical(v));
                    }
                    _ => {
                        b.extra.insert(k, v.into());
                    }
                }
            }
        }
        if !trigger {
            if let Some(h) = hold.filter(|h| mouse_key(h)) {
                b.trigger = h;
            }
        }
        if !scope && !b.target.is_empty() {
            b.scope = "restricted".into();
        }
        b.validate()?;
        Ok(b)
    }
    pub fn validate(&self) -> Result<(), String> {
        if !["restricted", "anywhere"].contains(&self.scope.as_str()) {
            return Err("Scope must be restricted or anywhere".into());
        }
        if !mouse_key(&self.trigger) {
            return Err("Trigger must be MOUSE1–MOUSE5".into());
        }
        let mut seen = HashSet::new();
        for action in ACTIONS {
            let key = self.keys.get(action).ok_or("Missing shortcut")?;
            if key_vk(key).is_none() {
                return Err(format!("Unsupported shortcut: {key}"));
            }
            if !seen.insert(canonical(key)) {
                return Err(format!("Duplicate shortcut: {key}"));
            }
        }
        Ok(())
    }
    pub fn text(&self) -> String {
        let mut text = String::from("# Kirby Clicker keybinds\n");
        for a in ACTIONS {
            text.push_str(&format!("{a}={}\n", self.keys[a]));
        }
        text.push_str(&format!(
            "trigger={}\nscope={}\ntarget={}\n",
            self.trigger, self.scope, self.target
        ));
        for (k, v) in &self.extra {
            text.push_str(&format!("{k}={v}\n"));
        }
        text
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn aliases_and_duplicates() {
        assert_eq!(key_vk("num3"), Some(0x63));
        assert!(Binds::parse("record=F9").is_err());
        assert!(Binds::parse("trigger=F7").is_err());
    }
    #[test]
    fn legacy_mouse_hold_migrates() {
        let b = Binds::parse("hold=RMB\ntarget=game.exe").unwrap();
        assert_eq!(b.trigger, "MOUSE2");
        assert_eq!(b.scope, "restricted");
        assert_eq!(Binds::parse("hold=SPACE").unwrap().trigger, "MOUSE1");
    }
}
