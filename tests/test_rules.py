"""Tests for hyacine.pipeline.rules."""
from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hyacine.models import CategoryHint, EmailMessage
from hyacine.pipeline.rules import (
    Rule,
    RuleSet,
    compile_subject_regex,
    load_rules,
    validate_rules_yaml,
)


def _email(
    *,
    sender_email: str = "test@example.com",
    sender_domain: str = "example.com",
    subject: str = "Hello",
) -> EmailMessage:
    return EmailMessage(
        id="msg-1",
        subject=subject,
        sender_email=sender_email,
        sender_domain=sender_domain,
        received_at=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Rule.matches — individual matcher tests
# ---------------------------------------------------------------------------

class TestRuleMatches:
    def test_sender_domain_substring_match(self) -> None:
        rule = Rule(name="r", category=CategoryHint.ARXIV, sender_domain="arxiv.org")
        email = _email(sender_domain="arxiv.org")
        assert rule.matches(email) is True

    def test_sender_domain_no_match(self) -> None:
        rule = Rule(name="r", category=CategoryHint.ARXIV, sender_domain="arxiv.org")
        email = _email(sender_domain="example.com")
        assert rule.matches(email) is False

    def test_sender_email_substring_match(self) -> None:
        # "noreply@" is a substring of "noreply@foo.com"
        rule = Rule(name="r", category=CategoryHint.NEWSLETTER, sender_email="noreply@")
        email = _email(sender_email="noreply@foo.com")
        assert rule.matches(email) is True

    def test_sender_email_case_insensitive(self) -> None:
        rule = Rule(name="r", category=CategoryHint.ADVISOR, sender_email="PRIYA@acme.example.com")
        email = _email(sender_email="priya@acme.example.com")
        assert rule.matches(email) is True

    def test_sender_email_no_match(self) -> None:
        rule = Rule(name="r", category=CategoryHint.ADVISOR, sender_email="priya@acme.example.com")
        email = _email(sender_email="other@example.com")
        assert rule.matches(email) is False

    def test_subject_regex_match(self) -> None:
        rule = Rule(name="r", category=CategoryHint.CFP, subject_regex=r"call for papers")
        email = _email(subject="CALL FOR PAPERS - NeurIPS 2025")
        assert rule.matches(email) is True

    def test_subject_regex_no_match(self) -> None:
        rule = Rule(name="r", category=CategoryHint.CFP, subject_regex=r"call for papers")
        email = _email(subject="Seminar announcement")
        assert rule.matches(email) is False

    def test_all_matchers_none_returns_false(self) -> None:
        rule = Rule(name="r", category=CategoryHint.OTHER)
        email = _email()
        assert rule.matches(email) is False

    def test_and_matching_both_must_match(self) -> None:
        rule = Rule(
            name="r",
            category=CategoryHint.GRAD_SCHOOL,
            sender_domain="acme.example.com",
            subject_regex=r"phd milestone",
        )
        # domain matches but subject does not
        email_bad = _email(sender_domain="acme.example.com", subject="Regular update")
        assert rule.matches(email_bad) is False

        # subject matches but domain does not
        email_bad2 = _email(sender_domain="gmail.com", subject="PhD Milestone Check")
        assert rule.matches(email_bad2) is False

        # both match
        email_good = _email(sender_domain="acme.example.com", subject="PhD Milestone Reminder")
        assert rule.matches(email_good) is True

    def test_and_matching_domain_plus_subject(self) -> None:
        rule = Rule(
            name="r",
            category=CategoryHint.CANVAS,
            sender_domain="instructure.com",
            subject_regex=r"\[canvas\]",
        )
        email = _email(sender_domain="instructure.com", subject="[Canvas] Assignment due")
        assert rule.matches(email) is True


# ---------------------------------------------------------------------------
# Happy-path classification for each CategoryHint
# ---------------------------------------------------------------------------

class TestRuleSetClassify:
    def _make_ruleset(self) -> RuleSet:
        return RuleSet(
            rules=[
                Rule(name="advisor", category=CategoryHint.ADVISOR,
                     sender_email="priya@acme.example.com"),
                Rule(name="grad-school", category=CategoryHint.GRAD_SCHOOL,
                     subject_regex=r"qualifying exam"),
                Rule(name="arxiv", category=CategoryHint.ARXIV,
                     sender_domain="arxiv.org"),
                Rule(name="scholar", category=CategoryHint.SCHOLAR,
                     sender_domain="scholar.google.com"),
                Rule(name="cfp", category=CategoryHint.CFP,
                     subject_regex=r"call for papers"),
                Rule(name="canvas", category=CategoryHint.CANVAS,
                     sender_domain="instructure.com"),
                Rule(name="admin", category=CategoryHint.ADMIN,
                     sender_domain="acme.example.com"),
                Rule(name="newsletter", category=CategoryHint.NEWSLETTER,
                     subject_regex=r"newsletter"),
            ]
        )

    def test_classify_advisor(self) -> None:
        rs = self._make_ruleset()
        email = _email(sender_email="priya@acme.example.com",
                       sender_domain="acme.example.com")
        assert rs.classify(email) == CategoryHint.ADVISOR

    def test_classify_grad_school(self) -> None:
        rs = self._make_ruleset()
        email = _email(subject="Qualifying Exam Reminder")
        assert rs.classify(email) == CategoryHint.GRAD_SCHOOL

    def test_classify_arxiv(self) -> None:
        rs = self._make_ruleset()
        email = _email(sender_domain="arxiv.org")
        assert rs.classify(email) == CategoryHint.ARXIV

    def test_classify_scholar(self) -> None:
        rs = self._make_ruleset()
        email = _email(sender_domain="scholar.google.com")
        assert rs.classify(email) == CategoryHint.SCHOLAR

    def test_classify_cfp(self) -> None:
        rs = self._make_ruleset()
        email = _email(subject="Call for Papers - VLDB 2026")
        assert rs.classify(email) == CategoryHint.CFP

    def test_classify_canvas(self) -> None:
        rs = self._make_ruleset()
        email = _email(sender_domain="instructure.com")
        assert rs.classify(email) == CategoryHint.CANVAS

    def test_classify_admin(self) -> None:
        rs = self._make_ruleset()
        email = _email(sender_domain="acme.example.com")
        assert rs.classify(email) == CategoryHint.ADMIN

    def test_classify_newsletter(self) -> None:
        rs = self._make_ruleset()
        email = _email(subject="Your weekly newsletter")
        assert rs.classify(email) == CategoryHint.NEWSLETTER

    def test_classify_defaults_to_other(self) -> None:
        rs = self._make_ruleset()
        email = _email(sender_email="stranger@gmail.com",
                       sender_domain="gmail.com",
                       subject="Random subject")
        assert rs.classify(email) == CategoryHint.OTHER

    def test_first_matching_rule_wins(self) -> None:
        # advisor rule is first; even though acme.example.com also matches admin,
        # advisor should win for priya
        rs = self._make_ruleset()
        email = _email(sender_email="priya@acme.example.com",
                       sender_domain="acme.example.com")
        assert rs.classify(email) == CategoryHint.ADVISOR


# ---------------------------------------------------------------------------
# load_rules with temp yaml file
# ---------------------------------------------------------------------------

class TestLoadRules:
    def test_load_rules_from_file(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            rules:
              - name: test-arxiv
                category: arxiv
                sender_domain: arxiv.org
              - name: test-advisor
                category: advisor
                sender_email: advisor@uni.edu
        """)
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(yaml_content)

        ruleset = load_rules(rules_file)
        assert len(ruleset.rules) == 2
        assert ruleset.rules[0].name == "test-arxiv"
        assert ruleset.rules[0].category == CategoryHint.ARXIV
        assert ruleset.rules[1].category == CategoryHint.ADVISOR

    def test_load_rules_classifies_correctly(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            rules:
              - name: arxiv-test
                category: arxiv
                sender_domain: arxiv.org
        """)
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(yaml_content)
        ruleset = load_rules(rules_file)

        email = _email(sender_domain="arxiv.org")
        assert ruleset.classify(email) == CategoryHint.ARXIV

    def test_load_rules_invalid_category_raises(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            rules:
              - name: bad
                category: nonexistent_category
                sender_domain: foo.com
        """)
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(yaml_content)
        with pytest.raises(ValueError, match="Invalid rules YAML"):
            load_rules(rules_file)

    def test_load_rules_missing_required_field_raises(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            rules:
              - name: bad-rule
                sender_domain: foo.com
        """)
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(yaml_content)
        with pytest.raises(ValueError, match="Invalid rules YAML"):
            load_rules(rules_file)


# ---------------------------------------------------------------------------
# validate_rules_yaml
# ---------------------------------------------------------------------------

class TestValidateRulesYaml:
    def test_valid_yaml_returns_ruleset(self) -> None:
        yaml_text = textwrap.dedent("""\
            rules:
              - name: r1
                category: admin
                sender_domain: example.com
        """)
        ruleset = validate_rules_yaml(yaml_text)
        assert isinstance(ruleset, RuleSet)
        assert len(ruleset.rules) == 1

    def test_invalid_schema_raises_value_error(self) -> None:
        yaml_text = textwrap.dedent("""\
            rules:
              - name: bad
                category: not_a_valid_category
                sender_domain: foo.com
        """)
        with pytest.raises(ValueError):
            validate_rules_yaml(yaml_text)

    def test_invalid_yaml_syntax_raises_value_error(self) -> None:
        yaml_text = "rules:\n  - name: [unclosed"
        with pytest.raises(ValueError):
            validate_rules_yaml(yaml_text)

    def test_empty_yaml_returns_empty_ruleset(self) -> None:
        ruleset = validate_rules_yaml("")
        assert isinstance(ruleset, RuleSet)
        assert ruleset.rules == []


# ---------------------------------------------------------------------------
# compile_subject_regex
# ---------------------------------------------------------------------------

class TestCompileSubjectRegex:
    def test_compiles_pattern(self) -> None:
        pat = compile_subject_regex(r"call for papers")
        assert pat.search("CALL FOR PAPERS 2025") is not None

    def test_case_insensitive(self) -> None:
        pat = compile_subject_regex(r"arxiv")
        assert pat.search("ArXiv digest") is not None

    def test_no_match(self) -> None:
        pat = compile_subject_regex(r"arxiv")
        assert pat.search("regular email") is None
