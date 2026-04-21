//! OS keychain helpers.
//!
//! All secrets live under the `hyacine` service name, keyed by a short slug
//! (`claude`, `ntfy`, `healthchecks`, …). A successful `set` is idempotent —
//! callers that need to rotate a key just call `set` again.

use keyring::Entry;

use crate::error::{AppError, AppResult};

const SERVICE: &str = "hyacine";

fn entry(slug: &str) -> AppResult<Entry> {
    Entry::new(SERVICE, slug).map_err(AppError::from)
}

pub fn set(slug: &str, value: &str) -> AppResult<()> {
    let e = entry(slug)?;
    e.set_password(value).map_err(AppError::from)?;
    Ok(())
}

pub fn has(slug: &str) -> AppResult<bool> {
    match entry(slug)?.get_password() {
        Ok(v) => Ok(!v.is_empty()),
        Err(keyring::Error::NoEntry) => Ok(false),
        Err(e) => Err(AppError::from(e)),
    }
}

pub fn get(slug: &str) -> AppResult<Option<String>> {
    match entry(slug)?.get_password() {
        Ok(v) => Ok(Some(v)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(AppError::from(e)),
    }
}

pub fn remove(slug: &str) -> AppResult<()> {
    match entry(slug)?.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(AppError::from(e)),
    }
}
