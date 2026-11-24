use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, fs, io, path::Path};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub auto_min_cps: f64,
    pub auto_max_cps: f64,
    pub auto_method: String,
    pub auto_sigma: f64,
    pub auto_button: String,
    pub click_backend: String,
    pub active_tab: u8,
    pub compact_enabled: bool,
    pub music_enabled: bool,
    pub music_volume: f64,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}
impl Default for Settings {
    fn default() -> Self {
        Self {
            auto_min_cps: 8.,
            auto_max_cps: 14.,
            auto_method: "blatant".into(),
            auto_sigma: 0.15,
            auto_button: "left".into(),
            click_backend: "foreground".into(),
            active_tab: 0,
            compact_enabled: false,
            music_enabled: true,
            music_volume: 0.05,
            extra: BTreeMap::new(),
        }
    }
}
fn clamp(value: f64, low: f64, high: f64, default: f64) -> f64 {
    if value.is_finite() {
        value.clamp(low, high)
    } else {
        default
    }
}
impl Settings {
    pub fn validate(&mut self) {
        self.auto_min_cps = clamp(self.auto_min_cps, 1., 50., 8.);
        self.auto_max_cps = clamp(self.auto_max_cps, self.auto_min_cps, 50., self.auto_min_cps);
        self.auto_sigma = clamp(self.auto_sigma, 0.05, 0.4, 0.15);
        self.music_volume = clamp(self.music_volume, 0., 1., 0.05);
        if !crate::METHODS.contains(&self.auto_method.as_str()) {
            self.auto_method = "blatant".into();
        }
        if !["left", "right", "middle"].contains(&self.auto_button.as_str()) {
            self.auto_button = "left".into();
        }
        if !["foreground", "background"].contains(&self.click_backend.as_str()) {
            self.click_backend = "foreground".into();
        }
        self.active_tab = self.active_tab.min(1);
    }
    pub fn load(path: &Path) -> Self {
        // Validate known keys individually: one malformed field must not discard
        // unrelated user preferences, including settings from the Python build.
        let mut base = serde_json::to_value(Self::default()).unwrap();
        if let Ok(serde_json::Value::Object(values)) = fs::read(path)
            .map_err(|_| ())
            .and_then(|b| serde_json::from_slice(&b).map_err(|_| ()))
        {
            let object = base.as_object_mut().unwrap();
            for (key, value) in values {
                if key == "active_tab" {
                    if let Some(n) = value.as_i64() {
                        object.insert(key, serde_json::json!(n.clamp(0, 1)));
                    }
                    continue;
                }
                let accepted = match object.get(&key) {
                    Some(serde_json::Value::Number(_)) => value.is_number(),
                    Some(serde_json::Value::String(_)) => value.is_string(),
                    Some(serde_json::Value::Bool(_)) => value.is_boolean(),
                    _ => true,
                };
                if accepted {
                    object.insert(key, value);
                }
            }
        }
        let mut result: Self = serde_json::from_value(base).unwrap_or_default();
        result.validate();
        result
    }
    pub fn save(&self, path: &Path) -> io::Result<()> {
        let mut settings = self.clone();
        settings.validate();
        let tmp = path.with_extension("json.tmp");
        fs::write(&tmp, serde_json::to_vec_pretty(&settings)?)?;
        #[cfg(windows)]
        {
            use std::os::windows::ffi::OsStrExt;
            use windows_sys::Win32::Storage::FileSystem::{
                MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH, MoveFileExW,
            };
            let from: Vec<_> = tmp.as_os_str().encode_wide().chain(Some(0)).collect();
            let to: Vec<_> = path.as_os_str().encode_wide().chain(Some(0)).collect();
            // SAFETY: both paths are NUL-terminated and live for this call.
            if unsafe {
                MoveFileExW(
                    from.as_ptr(),
                    to.as_ptr(),
                    MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
                )
            } == 0
            {
                return Err(io::Error::last_os_error());
            }
        }
        #[cfg(not(windows))]
        fs::rename(tmp, path)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn method_ids_survive_serialization() {
        for method in crate::METHODS {
            let mut s = Settings::default();
            s.auto_method = method.into();
            s.validate();
            let s: Settings = serde_json::from_slice(&serde_json::to_vec(&s).unwrap()).unwrap();
            assert_eq!(s.auto_method, method);
        }
    }
    #[test]
    fn validates_untrusted_values() {
        let mut s = Settings::default();
        s.auto_min_cps = f64::NAN;
        s.auto_max_cps = 999.;
        s.music_volume = -3.;
        s.validate();
        assert_eq!(s.auto_min_cps, 8.);
        assert_eq!(s.auto_max_cps, 50.);
        assert_eq!(s.music_volume, 0.);
    }
    #[test]
    fn preserves_python_geometry() {
        let s: Settings =
            serde_json::from_str(r#"{"window_geometry":"abc","compact_pos":[1,2]}"#).unwrap();
        let json = serde_json::to_value(s).unwrap();
        assert_eq!(json["window_geometry"], "abc");
    }
    #[test]
    fn malformed_field_does_not_reset_other_preferences() {
        let path = std::env::temp_dir().join(format!("kirby-settings-{}.json", std::process::id()));
        fs::write(&path,r#"{"active_tab":-500,"auto_min_cps":40,"auto_max_cps":50,"music_enabled":false,"auto_method":"static","window_geometry":"legacy"}"#).unwrap();
        let s = Settings::load(&path);
        assert_eq!(s.active_tab, 0);
        assert_eq!(s.auto_min_cps, 40.);
        assert!(!s.music_enabled);
        assert_eq!(s.auto_method, "static");
        s.save(&path).unwrap();
        let again = Settings::load(&path);
        assert_eq!(again.extra["window_geometry"], "legacy");
        assert_eq!(again.auto_max_cps, 50.);
        fs::remove_file(path).unwrap();
    }
}
