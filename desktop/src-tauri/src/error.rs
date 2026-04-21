use serde::{Serialize, Serializer};

/// Unified error type surfaced to the webview via `invoke()`.
/// Frontend receives `{kind, message}` JSON so it can branch on failure mode.
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("sidecar: {0}")]
    Sidecar(String),
    #[error("keyring: {0}")]
    Keyring(String),
    #[error("network: {0}")]
    Network(String),
    #[error("serde: {0}")]
    Serde(#[from] serde_json::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("other: {0}")]
    Other(String),
}

impl AppError {
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Sidecar(_) => "sidecar",
            Self::Keyring(_) => "keyring",
            Self::Network(_) => "network",
            Self::Serde(_) => "serde",
            Self::Io(_) => "io",
            Self::Other(_) => "other",
        }
    }
}

impl From<keyring::Error> for AppError {
    fn from(e: keyring::Error) -> Self {
        AppError::Keyring(e.to_string())
    }
}

impl From<reqwest::Error> for AppError {
    fn from(e: reqwest::Error) -> Self {
        AppError::Network(e.to_string())
    }
}

impl Serialize for AppError {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeStruct;
        let mut st = s.serialize_struct("AppError", 2)?;
        st.serialize_field("kind", self.kind())?;
        st.serialize_field("message", &self.to_string())?;
        st.end()
    }
}

pub type AppResult<T> = Result<T, AppError>;
