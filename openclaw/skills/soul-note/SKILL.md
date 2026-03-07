---
name: soul-note
description: Manage and access the independent Soul Note (self-reflection log), which automatically compresses daily discoveries and mood overviews.
metadata:
  {
    "openclaw":
      {
        "emoji": "📔"
      }
  }
---

# Soul Note

This skill lets you (the agent) add quick notes, discoveries, memory updates, or reflections directly into the independent `soul_notes.json` log. The system automatically handles their aggregation into `soul_reflections.json`.

## When to use

**CRITICAL DISTINCTION:**
A `Soul Note` is your **dynamic diary, event tracker, and daily reflection system**. It is completely different from `SOUL.md` (which is your fixed, core personality configuration).

Use this `soul-note` skill ONLY when:
- You discover a hidden truth, pattern, or interesting fact about the user that isn't simple enough for the procedural memory but doesn't warrant changing your core persona.
- You want to drop a "bookmark," daily journal entry, or an internal dialogue note about your current emotional state.
- The user asks you to log something to your soul diary, create a daily reflection, or write a "soul note".
- DO NOT use this to alter your own personality traits or system rules (use `edit-soul` for that).

## Quick start

To add a new note:
```bash
python scripts/soul_note_skill.py add "I just noticed the user prefers concise answers under stress." --category discovery --tags pattern,observation
```
Valid categories are: `reflection`, `discovery`, `error`, `memory_update`, `neurochemistry`.

To read today's notes:
```bash
python scripts/soul_note_skill.py today
```

To view recent major reflections:
```bash
python scripts/soul_note_skill.py list
```

*Note: You must run the command from the root of the openSOUL project tree using the `exec` tool.*
