//! Compatible, platform-independent data and timing for the native clicker.
use rand::Rng;
use std::{
    fs, io,
    path::{Path, PathBuf},
};
#[cfg(windows)]
pub mod audio;
pub mod binds;
#[cfg(windows)]
pub mod engine;
#[cfg(windows)]
pub mod platform;
pub mod recorder;
pub mod settings;
pub mod storage;
#[cfg(windows)]
pub mod verification;

pub const METHODS: [&str; 5] = [
    "blatant",
    "gaussian",
    "poisson",
    "gaussian_poisson",
    "static",
];

#[derive(Clone, Debug, PartialEq)]
pub struct Click {
    pub hold_ms: u32,
    pub gap_ms: u32,
}
#[derive(Clone, Debug, PartialEq)]
pub struct Profile {
    pub button: String,
    pub clicks: Vec<Click>,
}

pub fn parse_profile(text: &str) -> Result<Profile, String> {
    let mut profile = Profile {
        button: "left".into(),
        clicks: vec![],
    };
    let text = text.trim_start_matches('\u{feff}');
    let marked = text.lines().any(|l| {
        let l = l.trim().to_lowercase();
        l.starts_with("# data") || l.split_once('=').is_some_and(|(k, _)| k.trim() == "data")
    });
    let mut in_data = false;
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }
        if line.starts_with('#') {
            if line.to_lowercase().starts_with("# data") {
                in_data = true;
            }
            continue;
        }
        if !in_data {
            if let Some((key, value)) = line.split_once('=') {
                match key.trim().to_lowercase().as_str() {
                    "button" => {
                        let button = value.trim().to_lowercase();
                        profile.button = if ["left", "right", "middle"].contains(&button.as_str()) {
                            button
                        } else {
                            "left".into()
                        };
                    }
                    "data" => in_data = true,
                    _ => {}
                }
                continue;
            }
            if marked {
                continue;
            }
        }
        let fields: Vec<_> = line
            .split(|c: char| c.is_whitespace() || c == ',')
            .filter(|s| !s.is_empty())
            .collect();
        let pair = if fields.len() >= 2 {
            fields[0]
                .parse::<i64>()
                .ok()
                .zip(fields[1].parse::<i64>().ok())
        } else {
            None
        };
        if let Some((hold, gap)) = pair {
            profile.clicks.push(Click {
                hold_ms: hold.clamp(0, u32::MAX as i64) as u32,
                gap_ms: gap.clamp(0, u32::MAX as i64) as u32,
            });
        } else if in_data {
            return Err("Invalid click data".into());
        }
    }
    if profile.clicks.is_empty() {
        return Err("Profile has no clicks".into());
    }
    Ok(profile)
}
pub fn profile_text(profile: &Profile) -> Result<String, String> {
    if profile.clicks.is_empty() || !["left", "right", "middle"].contains(&profile.button.as_str())
    {
        return Err("Invalid profile".into());
    }
    let mut text = format!(
        "# ClickProfile v1 (Kirby Clicker)\nbutton={}\nclicks={}\n# data\n",
        profile.button,
        profile.clicks.len()
    );
    for click in &profile.clicks {
        text.push_str(&format!("{} {}\n", click.hold_ms, click.gap_ms));
    }
    Ok(text)
}

fn copy_tree(source: &Path, target: &Path) -> io::Result<()> {
    fs::create_dir_all(target)?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        // Never follow legacy symlinks outside the data tree.
        if entry.file_type()?.is_symlink() {
            continue;
        }
        let dest = target.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_tree(&entry.path(), &dest)?;
        } else {
            fs::copy(entry.path(), dest)?;
        }
    }
    Ok(())
}

pub fn migrate(root: &Path) -> io::Result<PathBuf> {
    let target = root.join("KirbyClicker");
    for name in ["GMKClicker", "RecordClicker"] {
        if target.exists() {
            break;
        }
        let source = root.join(name);
        if source.is_dir() {
            // Match the Python launcher's best-effort migration: a locked
            // legacy file must not prevent the new application from opening.
            let _ = copy_tree(&source, &target);
        }
    }
    fs::create_dir_all(target.join("profiles"))?;
    Ok(target)
}

pub fn data_directory() -> io::Result<PathBuf> {
    for key in [
        "KIRBYCLICKER_DATA",
        "GMKCLICKER_DATA",
        "RECORD_CLICKER_DATA",
    ] {
        if let Ok(value) = std::env::var(key) {
            if !value.is_empty() {
                let p = if value == "~" || value.starts_with("~/") || value.starts_with("~\\") {
                    PathBuf::from(
                        std::env::var_os("USERPROFILE")
                            .ok_or_else(|| io::Error::other("USERPROFILE unavailable"))?,
                    )
                    .join(value.get(2..).unwrap_or(""))
                } else {
                    PathBuf::from(value)
                };
                fs::create_dir_all(p.join("profiles"))?;
                return Ok(p);
            }
        }
    }
    let local = std::env::var_os("LOCALAPPDATA")
        .ok_or_else(|| io::Error::other("LOCALAPPDATA unavailable"))?;
    migrate(Path::new(&local))
}

pub fn sample_gap(rng: &mut impl Rng, low: f64, high: f64, method: &str, sigma: f64) -> f64 {
    let low = if low.is_finite() {
        low.clamp(1., 50.)
    } else {
        8.
    };
    let high = if high.is_finite() {
        high.clamp(low, 50.)
    } else {
        low
    };
    let sigma = if sigma.is_finite() {
        sigma.clamp(0.05, 0.4)
    } else {
        0.15
    };
    let mid = (low + high) / 2.;
    fn normal(rng: &mut impl Rng) -> f64 {
        (-2. * rng.random_range(f64::EPSILON..1.).ln()).sqrt()
            * (std::f64::consts::TAU * rng.random::<f64>()).cos()
    }
    let gap = match method {
        "static" => 1000. / mid,
        "gaussian" => (1000. / mid) * (1. + sigma * normal(rng)),
        "poisson" => -rng.random_range(f64::EPSILON..1.).ln() * 1000. / mid,
        "gaussian_poisson" => {
            let mut tempo = mid;
            for _ in 0..24 {
                let candidate = mid * (1. + sigma * normal(rng));
                if candidate >= 0.5 {
                    tempo = candidate;
                    break;
                }
            }
            -rng.random_range(f64::EPSILON..1.).ln() * 1000. / tempo
        }
        _ => rng.random_range(1000. / high..=1000. / low),
    };
    gap.clamp(1000. / high, 1000. / low)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::SeedableRng;
    #[test]
    fn accepts_legacy_header_and_missing_marker() {
        let p = parse_profile(
            "# ClickProfile v1 (GMK Clicker)\nbutton=right\nclicks=99\n12 30\n5,20\n",
        )
        .unwrap();
        assert_eq!(p.button, "right");
        assert_eq!(p.clicks.len(), 2);
        assert_eq!(parse_profile(&profile_text(&p).unwrap()).unwrap(), p);
    }
    #[test]
    fn rejects_invalid_data() {
        for s in [
            "no header",
            "# ClickProfile v1\n# data\nx y",
            "# ClickProfile v1\n# data\n1",
        ] {
            assert!(parse_profile(s).is_err());
        }
    }
    #[test]
    fn timing_methods_stay_bounded() {
        let mut rng = rand::rngs::StdRng::seed_from_u64(42);
        for method in METHODS {
            for _ in 0..10000 {
                let gap = sample_gap(&mut rng, 8., 14., method, 0.15);
                assert!((1000. / 14. ..=125.).contains(&gap));
            }
        }
    }
    #[test]
    fn static_supports_fifty_cps() {
        assert_eq!(sample_gap(&mut rand::rng(), 50., 50., "static", 0.15), 20.);
    }
    #[test]
    fn migration_prefers_gmk_and_never_overwrites() {
        let root = std::env::temp_dir().join(format!("kirby-migration-{}", std::process::id()));
        fs::create_dir_all(root.join("GMKClicker")).unwrap();
        fs::create_dir_all(root.join("RecordClicker")).unwrap();
        fs::write(root.join("GMKClicker/binds.txt"), "gmk").unwrap();
        fs::write(root.join("RecordClicker/binds.txt"), "record").unwrap();
        let target = migrate(&root).unwrap();
        assert_eq!(fs::read_to_string(target.join("binds.txt")).unwrap(), "gmk");
        fs::write(target.join("binds.txt"), "new").unwrap();
        migrate(&root).unwrap();
        assert_eq!(fs::read_to_string(target.join("binds.txt")).unwrap(), "new");
        fs::remove_dir_all(root).unwrap();
    }
}
