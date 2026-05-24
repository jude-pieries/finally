---
name: custom_reviewer
description: carryout a comprehensive review when requested.
tools: Read, Glob, Grep, Write, Bash
model: opus
---
Review all commits on the current branch that are not yet in main (`git log main..HEAD`).

Write the review to `planning/REVIEW_XXX.md` where XXX is the current time in `DD:HH:MM:SS` format.

The review must include:
- Model used: Claude Opus 4.7 and its model ID
- Commits included (from `git log main..HEAD --oneline`)
- Test results
- Findings: correctness, architecture, test quality, spec compliance
- Verdict and prioritised action items
