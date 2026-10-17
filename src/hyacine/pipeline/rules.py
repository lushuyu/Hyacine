"""Rule-based pre-classification (category_hint).

Rules loaded from config/rules.yaml. First match wins. A rule with multiple
matchers requires ALL to match (AND). Empty / whitespace-only matchers count
as unset.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, PrivateAttr, ValidationError, field_validator

from hyacine.models import CategoryHint, EmailMessage


class Rule(BaseModel):
    name: str
    category: CategoryHint
    sender_domain: str | None = None
    sender_email: str | None = None
    subject_regex: str | None = None

    # Compiled once from subject_regex in model_post_init, not per email.
    _subject_pattern: re.Pattern[str] | None = PrivateAttr(default=None)

    @field_validator("sender_domain", "sender_email", "subject_regex", mode="before")
    @classmethod
    def _blank_matcher_is_unset(cls, value: Any) -> Any:
        """Treat an empty or whitespace-only matcher as unset (None).

        `"" in x` is True for every string, so a placeholder like
        `sender_email: ""` would otherwise match every email and, since the
        first match wins, swallow every rule below it.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("subject_regex")
    @classmethod
    def _subject_regex_compiles(cls, value: str | None) -> str | None:
        """Reject a bad pattern at load time instead of mid-run in matches()."""
        if value is not None:
            try:
                compile_subject_regex(value)
            except (re.error, OverflowError) as exc:
                raise ValueError(f"invalid subject_regex {value!r}: {exc}") from exc
        return value

    def model_post_init(self, context: Any, /) -> None:
        if self.subject_regex is not None:
            self._subject_pattern = compile_subject_regex(self.subject_regex)

    def matches(self, email: EmailMessage) -> bool:
        """Return True iff ALL configured matchers match the email.

        A rule with all matchers None matches nothing.
        """
        # Guard: a rule with no matchers matches nothing
        if self.sender_domain is None and self.sender_email is None and self.subject_regex is None:
            return False

        if self.sender_domain is not None:
            if self.sender_domain.lower() not in email.sender_domain.lower():
                return False

        if self.sender_email is not None:
            if self.sender_email.lower() not in email.sender_email.lower():
                return False

        if self._subject_pattern is not None:
            if not self._subject_pattern.search(email.subject):
                return False

        return True


class RuleSet(BaseModel):
    rules: list[Rule] = Field(default_factory=list)

    def classify(self, email: EmailMessage) -> CategoryHint:
        """Apply rules top-to-bottom; default to CategoryHint.OTHER."""
        for rule in self.rules:
            if rule.matches(email):
                return rule.category
        return CategoryHint.OTHER


def load_rules(path: Path) -> RuleSet:
    """Parse rules.yaml into a validated RuleSet. Raises on schema errors."""
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    try:
        return RuleSet(**data)
    except (ValidationError, TypeError) as exc:
        raise ValueError(f"Invalid rules YAML at {path}: {exc}") from exc


def validate_rules_yaml(yaml_text: str) -> RuleSet:
    """Parse-and-validate a yaml string (used by the Web editor)."""
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error: {exc}") from exc
    try:
        return RuleSet(**data)
    except (ValidationError, TypeError) as exc:
        raise ValueError(f"Invalid rules schema: {exc}") from exc


def compile_subject_regex(pattern: str) -> re.Pattern[str]:
    """Compile with IGNORECASE. Shared by Rule validation/matching and tests."""
    return re.compile(pattern, re.IGNORECASE)


__all__ = ["Rule", "RuleSet", "load_rules", "validate_rules_yaml", "compile_subject_regex"]
