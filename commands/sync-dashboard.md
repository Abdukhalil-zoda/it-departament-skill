---
description: Regenerate the project dashboard (vault/00-Dashboard.md) from the vault notes, reports and lock file, or check whether it is stale
argument-hint: [--check]
allowed-tools: Bash, PowerShell, Read, Glob
---

Regenerate or check the project dashboard. Arguments: `$ARGUMENTS` (`--check` reports staleness without writing).

1. Locate the project root (nearest `.it-department/config.json` upward from the current working directory) and
   the skill copy it uses (`<project>/.agents/skills/it-departament-skill`, `<project>/.claude/skills/it-departament-skill`,
   `~/.claude/skills/it-departament-skill`, else `${CLAUDE_PLUGIN_ROOT}`).
2. Respect the session protocol (`workflows/session-protocol.md`): read `.it-department/lock.json`; if another
   live session holds the lock, run only `--check` and report that the holder must sync.
3. Run `python3 <skill_root>/scripts/dashboard_sync.py --root <project> $ARGUMENTS` (`python` on Windows; without
   Python on the host use Docker: `docker run --rm -v "<skill_root>:/skill:ro" -v "<project>:/work" python:3.12-alpine python /skill/scripts/dashboard_sync.py --root /work $ARGUMENTS`).
4. Report the script's summary line (updated / up to date / would update), the warnings it printed (missing
   documents, unresolvable links, notes without frontmatter) with the fix for each, and remind that
   `apply_transitions.py` applies pending transition requests before the next sync.
