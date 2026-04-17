"""Rule-based pre-classification (category_hint).

Rules loaded from config/rules.yaml. First match wins. A rule with multiple
matchers requires ALL to match (AND).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from hyacine.models import CategoryHint, EmailMessage


class Rule(BaseModel):
    name: str
    category: CategoryHint
    sender_domain: str | None = None
    sender_email: str | None = None
    subject_regex: str | None = None

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

        if self.subject_regex is not None:
            if not re.search(self.subject_regex, email.subject, flags=re.IGNORECASE):
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
    """Compile with IGNORECASE. Separate helper so tests can exercise it."""
    return re.compile(pattern, re.IGNORECASE)


__all__ = ["Rule", "RuleSet", "load_rules", "validate_rules_yaml", "compile_subject_regex"]
