## Summary

<!--
1-3 bullet points describing WHAT changed and WHY.
-->

-
-
-

## Test plan

<!--
Bulleted checklist of what you tested. Be specific.
-->

- [ ]
- [ ]

## Screenshots / transcript (if UI/CLI change)

<!--
Paste terminal output or screenshots here if this changes user-visible behavior.
-->

---

## Pre-merge checklist

- [ ] `uv run ruff check .` passes locally
- [ ] `uv run mypy src/` passes locally
- [ ] `uv run pytest` passes locally
- [ ] `python scripts/scrub_check.py` passes locally
- [ ] Updated docs if behavior changed
- [ ] Added tests for new code paths
- [ ] Commit messages are imperative and explain WHY
