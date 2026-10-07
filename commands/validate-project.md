---
description: Validate the current project's IT Department setup (config contract, vault layout, vault lint) and explain how to fix each failure
argument-hint: [project-root]
allowed-tools: Bash, PowerShell, Read, Glob
---

Validate the IT Department project setup. Project root: `$ARGUMENTS` if given, otherwise the nearest directory
upward from the current working directory that contains `.it-department/config.json`.

1. Locate the skill copy used by the project (`<project>/.agents/skills/it-department-skill`,
   `<project>/.claude/skills/it-department-skill`, `~/.claude/skills/it-department-skill`) and fall back to this
   plugin (`${CLAUDE_PLUGIN_ROOT}`).
2. Run the validator: Windows `pwsh -NoProfile -File "<skill_root>/scripts/validate-project.ps1" -ProjectRoot "<project>"`,
   otherwise `bash "<skill_root>/scripts/validate-project.sh" "<project>"`. When Python is not available on the
   host and Docker is, also run the vault lint through Docker:
   `docker run --rm -v "<skill_root>:/skill:ro" -v "<project>:/work:ro" python:3.12-alpine python /skill/scripts/vault_lint.py --root /work --no-dashboard-check`.
3. Report every `[WARN]`, every failure and every lint finding grouped by cause, each with the concrete fix:
   a missing folder → re-run `init-project`; a config contract error → the key and the allowed values
   (`assets/project-config.schema.json`); a lint code → the note path and the field or folder to change
   (`references/definition-of-ready-done.md`). End with the overall verdict and the installed skill version
   printed by the validator.
