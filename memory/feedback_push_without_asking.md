---
name: feedback_push_without_asking
description: Never push to git without asking the user first
metadata:
  type: feedback
---

Always ask before running `git push`. Do not push automatically after committing.

**Why:** User explicitly asked not to be surprised by pushes.

**How to apply:** After committing, stop and ask "Should I push this?" before running any `git push` command.
