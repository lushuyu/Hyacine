# Example persona: Alice the PM

A concrete worked example of what `python -m hyacine init` produces. Alice is
a made-up Product Manager at "Acme Robotics" (also made up). Reading her files
is often faster than reading the template spec.

## Files

| File | Role |
|---|---|
| `config/config.yaml` | What the wizard writes to `./config/config.yaml`. |
| `config/rules.yaml` | Her category rules; compare with `config/rules.starter.yaml` to see the diff. |
| `prompts/hyacine.md` | Rendered prompt — what the wizard produces from `prompts/hyacine.md.template` given her answers. |

## Try it

Want to play with Alice's setup without running the wizard? Copy her files
into your repo tree:

```bash
cp examples/alice/config/config.yaml config/config.yaml
cp examples/alice/config/rules.yaml config/rules.yaml
cp examples/alice/prompts/hyacine.md prompts/hyacine.md
```

Then edit `config/config.yaml` to change `recipient_email` to your own
address (otherwise the pipeline will refuse to send). Follow the rest of
[ONBOARDING.md](../../docs/ONBOARDING.md) from step 3.

## What her prompt emphasises

- **Priorities**: commits from her direct reports, anything from her VP, calendar
  conflicts, incident pages.
- **Research section**: GitHub release feeds for the three OSS libraries her
  team ships on, plus Acme's internal design-doc digest.
- **Admin bucket**: JIRA tickets, HR-all-hands, expense reports.

These priorities are set in her identity blurb and priority list. Swap them
for whatever your life looks like.
