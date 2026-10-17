//! Guards for capabilities/default.json.
//!
//! The opener scope is an allow-list of URL globs. `openUrl` (and every
//! `target="_blank"` link, which the opener plugin intercepts) fails for a
//! URL outside it, so a provider docs link added without a matching entry
//! silently stops working. These tests catch that and keep the scope from
//! being widened to arbitrary hosts.

use std::path::{Path, PathBuf};

use regex::Regex;
use serde_json::Value;

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn capability() -> Value {
    let path = manifest_dir().join("capabilities").join("default.json");
    let body = std::fs::read_to_string(&path).expect("read capabilities/default.json");
    serde_json::from_str(&body).expect("parse capabilities/default.json")
}

fn opener_globs() -> Vec<String> {
    let cap = capability();
    let permissions = cap["permissions"].as_array().expect("permissions array");
    let opener: Vec<&Value> = permissions
        .iter()
        .filter(|p| p.get("identifier").and_then(Value::as_str) == Some("opener:allow-open-url"))
        .collect();
    assert_eq!(opener.len(), 1, "expected one scoped opener:allow-open-url entry");
    opener[0]["allow"]
        .as_array()
        .expect("opener allow list")
        .iter()
        .map(|e| e["url"].as_str().expect("url glob").to_string())
        .collect()
}

/// `*`-only glob match with the semantics tauri-plugin-opener uses
/// (`glob::Pattern::matches`, default options: `*` also matches `/`).
fn glob_match(pattern: &str, text: &str) -> bool {
    let parts: Vec<&str> = pattern.split('*').collect();
    if parts.len() == 1 {
        return pattern == text;
    }
    let (first, last) = (parts[0], parts[parts.len() - 1]);
    if text.len() < first.len() + last.len() || !text.starts_with(first) || !text.ends_with(last) {
        return false;
    }
    let mut middle = &text[first.len()..text.len() - last.len()];
    for part in &parts[1..parts.len() - 1] {
        match middle.find(part) {
            Some(i) => middle = &middle[i + part.len()..],
            None => return false,
        }
    }
    true
}

fn allowed(url: &str) -> bool {
    opener_globs().iter().any(|g| glob_match(g, url))
}

#[test]
fn webview_gets_only_the_permissions_it_uses() {
    let cap = capability();
    let names: Vec<String> = cap["permissions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| match p {
            Value::String(s) => s.clone(),
            other => other["identifier"].as_str().unwrap().to_string(),
        })
        .collect();
    assert_eq!(names, ["core:default", "opener:allow-open-url"]);
}

#[test]
fn opener_globs_pin_an_https_host() {
    for glob in opener_globs() {
        // Keep glob_match above equivalent to glob::Pattern.
        assert!(!glob.contains(['?', '[', ']']), "unsupported glob syntax in {glob}");
        let rest = glob.strip_prefix("https://").unwrap_or_else(|| panic!("{glob}: https only"));
        let host = rest.split('/').next().unwrap();
        assert!(
            !host.is_empty() && !host.contains('*') && rest.contains('/'),
            "{glob}: the host must be literal and followed by a path"
        );
    }
}

#[test]
fn device_login_pages_open() {
    for url in [
        "https://microsoft.com/devicelogin",
        "https://www.microsoft.com/devicelogin",
        "https://login.microsoft.com/device",
        "https://login.microsoftonline.com/common/oauth2/deviceauth",
    ] {
        assert!(allowed(url), "{url} should be allowed");
    }
}

#[test]
fn other_urls_stay_blocked() {
    for url in [
        "https://evil.example/",
        "https://microsoft.com.evil.example/devicelogin",
        "https://login.microsoftonline.com.evil.example/",
        "http://microsoft.com/devicelogin",
        "file:///etc/passwd",
        "mailto:someone@example.com",
    ] {
        assert!(!allowed(url), "{url} should be blocked");
    }
}

fn docs_urls(path: &Path, pattern: &str) -> Option<Vec<String>> {
    let body = std::fs::read_to_string(path).ok()?;
    let re = Regex::new(pattern).unwrap();
    Some(re.captures_iter(&body).map(|c| c[1].to_string()).collect())
}

#[test]
fn provider_docs_links_open() {
    let repo = manifest_dir().join("..").join("..");
    let sources = [
        (
            repo.join("src").join("hyacine").join("llm").join("providers.py"),
            r#"docs_url="([^"]+)""#,
        ),
        (
            repo.join("desktop").join("src").join("lib").join("provider-presets.ts"),
            r#"docs_url:\s*'([^']+)'"#,
        ),
    ];
    for (path, pattern) in sources {
        let Some(urls) = docs_urls(&path, pattern) else {
            eprintln!("skipping {}: not found", path.display());
            continue;
        };
        assert!(!urls.is_empty(), "no docs_url found in {}", path.display());
        for url in urls {
            assert!(
                allowed(&url),
                "{url} (from {}) needs an opener entry in capabilities/default.json",
                path.display()
            );
        }
    }
}

#[test]
fn glob_match_handles_wildcards() {
    assert!(glob_match("https://a.example/*", "https://a.example/"));
    assert!(glob_match("https://a.example/*", "https://a.example/x/y?z=1"));
    assert!(glob_match("https://a.example/x*", "https://a.example/x"));
    assert!(!glob_match("https://a.example/x*", "https://a.example/"));
    assert!(glob_match("a*b*c", "a-b-c"));
    assert!(!glob_match("a*b*c", "a-c"));
    assert!(glob_match("exact", "exact"));
    assert!(!glob_match("exact", "exact!"));
}
