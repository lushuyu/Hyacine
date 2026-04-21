//! Secret-scrubbing helpers used before any sidecar output hits tracing.
//!
//! The wider design promises that secrets only ever live in the keychain and
//! never in logs. The sidecar's stderr is the one place Python exceptions,
//! request bodies, or repr()ed state could surface a key by accident, so we
//! run each line through a regex pass before emitting it.

use once_cell::sync::Lazy;
use regex::Regex;

// Anthropic console keys ("sk-ant-<api03|oat01|…>-…"), Claude Code OAuth
// tokens ("sk-..-oat01-…"), and bare "Bearer <token>" headers that might
// appear in a traceback or stringified httpx Response.
static PATTERNS: Lazy<Vec<(Regex, &'static str)>> = Lazy::new(|| {
    vec![
        (
            Regex::new(r"sk-ant-[A-Za-z0-9_\-]{10,}").unwrap(),
            "sk-ant-[REDACTED]",
        ),
        (
            Regex::new(r"sk-[A-Za-z0-9]{0,4}-oat01-[A-Za-z0-9_\-]{10,}").unwrap(),
            "sk-…-oat01-[REDACTED]",
        ),
        (
            Regex::new(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}").unwrap(),
            "Bearer [REDACTED]",
        ),
    ]
});

/// Return a copy of `s` with known secret shapes replaced by marker strings.
pub fn scrub(s: &str) -> String {
    let mut out = s.to_string();
    for (re, repl) in PATTERNS.iter() {
        out = re.replace_all(&out, *repl).into_owned();
    }
    out
}

#[cfg(test)]
mod tests {
    use super::scrub;

    #[test]
    fn redacts_anthropic_api_keys() {
        let line = "x-api-key: sk-ant-api03-abcdefghijKLMNOPqrst_0123";
        assert_eq!(
            scrub(line),
            "x-api-key: sk-ant-[REDACTED]"
        );
    }

    #[test]
    fn redacts_bearer_tokens() {
        let line = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.x";
        assert_eq!(scrub(line), "Authorization: Bearer [REDACTED]");
    }

    #[test]
    fn leaves_regular_text_alone() {
        let line = "fetched 17 messages";
        assert_eq!(scrub(line), line);
    }
}
