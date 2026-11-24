//! Profile library operations and Python-compatible exchange v2.
use crate::{Click, Profile, parse_profile, profile_text};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
};

pub fn name_problem(name: &str) -> Option<&'static str> {
    if name.trim().is_empty() {
        return Some("Enter a name");
    }
    if name.chars().count() > 80 {
        return Some("Name is too long (80 characters maximum)");
    }
    if name.ends_with([' ', '.'])
        || name
            .chars()
            .any(|c| c.is_control() || "<>:\"/\\|?*".contains(c))
    {
        return Some("Name contains a character Windows cannot use");
    }
    let stem = name.split('.').next().unwrap_or("").to_uppercase();
    if ["CON", "PRN", "AUX", "NUL"].contains(&stem.as_str())
        || (stem.len() == 4
            && (stem.starts_with("COM") || stem.starts_with("LPT"))
            && matches!(stem.as_bytes()[3], b'1'..=b'9'))
    {
        return Some("Windows reserves this name");
    }
    None
}
fn clean_name(name: &str) -> String {
    let name: String = name
        .chars()
        .map(|c| {
            if c.is_control() {
                ' '
            } else if "<>:\"/\\|?*".contains(c) {
                '_'
            } else {
                c
            }
        })
        .collect();
    let mut name = name
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim_matches([' ', '.'])
        .chars()
        .take(75)
        .collect::<String>();
    if name.is_empty() {
        name = "imported-profile".into();
    }
    if name_problem(&name).is_some() {
        name = format!("profile-{name}");
    }
    name
}
pub fn library(dir: &Path) -> Vec<String> {
    let mut names: Vec<_> = fs::read_dir(dir)
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .filter(|e| {
            e.path().is_file()
                && e.path()
                    .extension()
                    .is_some_and(|s| s.eq_ignore_ascii_case("txt"))
        })
        .filter_map(|e| e.file_name().into_string().ok())
        .collect();
    names.sort_by_key(|s| s.to_lowercase());
    names
}
pub fn read(path: &Path) -> Result<Profile, String> {
    if fs::metadata(path).map_err(|e| e.to_string())?.len() > 32 * 1024 * 1024 {
        return Err("Profile exceeds 32 MB".into());
    }
    parse_profile(&String::from_utf8_lossy(
        &fs::read(path).map_err(|e| e.to_string())?,
    ))
}
pub fn save_new(dir: &Path, p: &Profile, base: Option<&str>) -> Result<PathBuf, String> {
    fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    let text = profile_text(p)?;
    for i in 0..100000 {
        let name = if let Some(base) = base {
            let base = clean_name(base);
            match i {
                0 => format!("{base}.txt"),
                1 => format!("{base} (imported).txt"),
                _ => format!("{base} (imported {i}).txt"),
            }
        } else {
            format!("rec{}.txt", i + 1)
        };
        let path = dir.join(name);
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(mut f) => {
                if let Err(e) = f.write_all(text.as_bytes()).and_then(|_| f.sync_all()) {
                    let _ = fs::remove_file(&path);
                    return Err(e.to_string());
                }
                return Ok(path);
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e.to_string()),
        }
    }
    Err("Could not find an unused profile name".into())
}
pub fn rename(dir: &Path, old: &str, new: &str) -> Result<String, String> {
    let new = new.trim().strip_suffix(".txt").unwrap_or(new.trim());
    if let Some(problem) = name_problem(new) {
        return Err(problem.into());
    }
    if Path::new(old).file_name().and_then(|s| s.to_str()) != Some(old) {
        return Err("Invalid source name".into());
    }
    let new = format!("{new}.txt");
    if new == old {
        return Ok(new);
    }
    let src = dir.join(old);
    let dst = dir.join(&new);
    // std::fs::rename does not replace an existing file on Windows. Explicitly
    // refuse it on all platforms so a typo cannot overwrite a recording.
    if dst.exists() {
        return Err("A profile with that name already exists".into());
    }
    fs::rename(src, dst).map_err(|e| e.to_string())?;
    Ok(new)
}
fn stats(p: &Profile) -> Value {
    let intervals: Vec<u64> = p
        .clicks
        .iter()
        .map(|c| c.hold_ms as u64 + c.gap_ms as u64)
        .collect();
    let sum: u64 = intervals.iter().sum();
    json!({"clicks":p.clicks.len(),"avg_cps":if sum==0{0.}else{1000.*p.clicks.len() as f64/sum as f64},"min_interval_ms":intervals.iter().min().copied().unwrap_or(0),"max_interval_ms":intervals.iter().max().copied().unwrap_or(0)})
}
fn checksum(v: &Value) -> String {
    format!(
        "sha256:{:x}",
        Sha256::digest(serde_json::to_vec(v).unwrap())
    )
}
fn validate(p: &Profile) -> Result<(), String> {
    if p.clicks.is_empty() || p.clicks.len() > 250000 {
        return Err("Profile must contain 1–250000 clicks".into());
    }
    if !["left", "right", "middle"].contains(&p.button.as_str()) {
        return Err("Unsupported button".into());
    }
    if p.clicks
        .iter()
        .any(|c| c.hold_ms > 60000 || c.gap_ms > 3600000)
    {
        return Err("Click duration exceeds exchange limits".into());
    }
    Ok(())
}
pub fn exchange(p: &Profile, name: &str) -> Result<Value, String> {
    validate(p)?;
    let mut v = json!({"format":"record-clicker-profile","version":2,"created_by":"Kirby Clicker 1.3.0","created_at":crate::platform::utc_now(),"profile":{"name":clean_name(name),"button":p.button,"clicks":p.clicks.iter().map(|c|[c.hold_ms,c.gap_ms]).collect::<Vec<_>>()},"stats":stats(p)});
    v["checksum"] = Value::String(checksum(&v));
    Ok(v)
}
pub fn export(path: &Path, p: &Profile, name: &str) -> Result<(), String> {
    let bytes = serde_json::to_vec_pretty(&exchange(p, name)?).map_err(|e| e.to_string())?;
    let tmp = path.with_file_name(format!(
        "{}.tmp",
        path.file_name().unwrap_or_default().to_string_lossy()
    ));
    let result = (|| -> std::io::Result<()> {
        let mut file = fs::File::create(&tmp)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        drop(file);
        crate::platform::replace_file(&tmp, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(tmp);
    }
    result.map_err(|e| e.to_string())
}
fn allowed(v: &Value, keys: &[&str]) -> bool {
    v.as_object()
        .is_some_and(|o| o.keys().all(|k| keys.contains(&k.as_str())))
}
pub fn decode_exchange(mut v: Value) -> Result<(Profile, String), String> {
    if !allowed(
        &v,
        &[
            "format",
            "version",
            "created_by",
            "created_at",
            "profile",
            "stats",
            "checksum",
        ],
    ) || v["format"] != "record-clicker-profile"
        || v["version"].as_u64() != Some(2)
    {
        return Err("Not an exchange v2 file".into());
    }
    let declared = v
        .as_object_mut()
        .unwrap()
        .remove("checksum")
        .and_then(|s| s.as_str().map(str::to_lowercase))
        .ok_or("Missing checksum")?;
    if declared != checksum(&v) {
        return Err("Checksum mismatch: file is corrupt or modified".into());
    }
    for k in ["created_by", "created_at"] {
        if v.get(k).is_some_and(|s| !s.is_string()) {
            return Err("Invalid creation metadata".into());
        }
    }
    if !allowed(&v["profile"], &["name", "button", "clicks"])
        || !allowed(
            &v["stats"],
            &["clicks", "avg_cps", "min_interval_ms", "max_interval_ms"],
        )
    {
        return Err("Unexpected profile/stat fields".into());
    }
    let name = v["profile"]["name"]
        .as_str()
        .ok_or("Missing profile name")?
        .to_string();
    let mut p = Profile {
        button: v["profile"]["button"]
            .as_str()
            .ok_or("Missing button")?
            .trim()
            .to_lowercase(),
        clicks: vec![],
    };
    let array = v["profile"]["clicks"].as_array().ok_or("Missing clicks")?;
    if array.len() > 250000 {
        return Err("Too many clicks".into());
    }
    for c in array {
        if c.as_array().is_none_or(|c| c.len() != 2) {
            return Err("Invalid click pair".into());
        }
        p.clicks.push(Click {
            hold_ms: c[0]
                .as_u64()
                .and_then(|n| u32::try_from(n).ok())
                .ok_or("Invalid hold")?,
            gap_ms: c[1]
                .as_u64()
                .and_then(|n| u32::try_from(n).ok())
                .ok_or("Invalid gap")?,
        });
    }
    validate(&p)?;
    let expected = stats(&p);
    for k in ["clicks", "min_interval_ms", "max_interval_ms"] {
        if v["stats"][k].as_u64() != expected[k].as_u64() {
            return Err("Stats do not match clicks".into());
        }
    }
    let avg = v["stats"]["avg_cps"]
        .as_f64()
        .ok_or("Invalid average CPS")?;
    if !avg.is_finite() || (avg - expected["avg_cps"].as_f64().unwrap()).abs() > 0.005 {
        return Err("Stats do not match clicks".into());
    }
    Ok((p, clean_name(&name)))
}
pub fn import(source: &Path, dir: &Path) -> Result<PathBuf, String> {
    if fs::metadata(source).map_err(|e| e.to_string())?.len() > 32 * 1024 * 1024 {
        return Err("Import exceeds 32 MB".into());
    }
    let text = fs::read_to_string(source).map_err(|e| e.to_string())?;
    let text = text.trim_start_matches('\u{feff}');
    let (p, name) = if text.trim_start().starts_with('{') {
        decode_exchange(serde_json::from_str(text).map_err(|e| e.to_string())?)?
    } else {
        let header = text
            .lines()
            .find(|l| !l.trim().is_empty())
            .unwrap_or("")
            .trim()
            .to_lowercase();
        let has_marker = text
            .lines()
            .any(|l| l.trim().to_lowercase().starts_with("# data"));
        let has_meta = text.lines().any(|l| {
            l.trim().to_lowercase().starts_with("button=")
                || l.trim().to_lowercase().starts_with("clicks=")
        });
        if !header.starts_with("# clickprofile v1") && !(has_marker && has_meta) {
            return Err("Not a legacy ClickProfile v1 file".into());
        }
        let p = parse_profile(text)?;
        validate(&p)?;
        let mut in_data = !has_marker;
        for l in text.lines().map(str::trim) {
            if l.to_lowercase().starts_with("# data") {
                in_data = true;
                continue;
            }
            if l.is_empty() || l.starts_with('#') {
                continue;
            }
            if let Some((k, v)) = l.split_once('=') {
                if k.trim() == "clicks" && v.trim().parse::<usize>().ok() != Some(p.clicks.len()) {
                    return Err("Declared click count does not match".into());
                }
                if k.trim() == "button"
                    && !["left", "right", "middle"].contains(&v.trim().to_lowercase().as_str())
                {
                    return Err("Invalid button".into());
                }
                continue;
            }
            if !in_data {
                continue;
            }
            let pair: Vec<_> = l.split_whitespace().collect();
            if pair.len() != 2
                || pair[0].parse::<u32>().ok().is_none_or(|n| n > 60000)
                || pair[1].parse::<u32>().ok().is_none_or(|n| n > 3600000)
            {
                return Err("Invalid legacy click data".into());
            }
        }
        (
            p,
            source
                .file_stem()
                .unwrap_or_default()
                .to_string_lossy()
                .into_owned(),
        )
    };
    save_new(dir, &p, Some(&name))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn export_replaces_an_existing_file_with_valid_exchange() {
        let path = std::env::temp_dir().join(format!("kirby-export-{}.json", std::process::id()));
        fs::write(&path, "previous").unwrap();
        let p = Profile {
            button: "middle".into(),
            clicks: vec![Click {
                hold_ms: 10,
                gap_ms: 40,
            }],
        };
        export(&path, &p, "New").unwrap();
        let v = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(decode_exchange(v).unwrap().0, p);
        fs::remove_file(path).unwrap();
    }
    #[test]
    fn reads_python_export_with_unicode_and_checksum() {
        let v = serde_json::from_str(include_str!("../tests/fixtures/python-v2.rcprofile.json"))
            .unwrap();
        let (p, name) = decode_exchange(v).unwrap();
        assert_eq!(p.button, "right");
        assert_eq!(p.clicks.len(), 2);
        assert_eq!(name, "Python profile 测试");
    }
    #[test]
    fn invalid_names_are_refused() {
        for n in ["", "CON", "con.txt", "a/b", "hello.", "LPT1"] {
            assert!(name_problem(n).is_some());
        }
    }
    #[test]
    fn exchange_detects_corruption() {
        let p = Profile {
            button: "left".into(),
            clicks: vec![Click {
                hold_ms: 12,
                gap_ms: 36,
            }],
        };
        let mut v = exchange(&p, "测试").unwrap();
        assert_eq!(decode_exchange(v.clone()).unwrap().0, p);
        v["profile"]["clicks"][0][0] = json!(99);
        assert!(decode_exchange(v).is_err());
    }
    #[test]
    fn new_recordings_and_imports_do_not_overwrite() {
        let d = std::env::temp_dir().join(format!("kirby-storage-{}", std::process::id()));
        fs::create_dir_all(&d).unwrap();
        let p = Profile {
            button: "left".into(),
            clicks: vec![Click {
                hold_ms: 1,
                gap_ms: 2,
            }],
        };
        let a = save_new(&d, &p, None).unwrap();
        let b = save_new(&d, &p, None).unwrap();
        assert_ne!(a, b);
        let x = save_new(&d, &p, Some("a")).unwrap();
        let y = save_new(&d, &p, Some("a")).unwrap();
        assert_ne!(x, y);
        assert!(rename(&d, "rec1.txt", "rec2").is_err());
        fs::remove_dir_all(d).unwrap();
    }
}
