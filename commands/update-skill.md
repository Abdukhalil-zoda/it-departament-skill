---
description: Update the IT Department skill used by this project to the latest version, re-run init and validate, and report the migration notes
argument-hint: [--check] [--ref <tag-or-branch>]
allowed-tools: Bash, PowerShell, Read, Glob
---

Update the IT Department skill that this project uses and apply its migration notes. Arguments: `$ARGUMENTS`
(`--check` only compares versions; `--ref <tag-or-branch>` pins the update target).

1. **Find the project root:** the nearest directory, searching upward from the current working directory, that
   contains `.it-department/config.json`. If there is none, say that the project is not initialised and stop
   (offer `init-project`).
2. **Find the skill copy the project uses**, in this order: `<project>/.agents/skills/it-departament-skill`,
   `<project>/.claude/skills/it-departament-skill`, `~/.claude/skills/it-departament-skill`. If none exists, the
   project relies on this plugin: run `claude plugin update it-departament-skill@it-departament`, then run
   `${CLAUDE_PLUGIN_ROOT}/scripts/init-project.ps1` (Windows) or `.sh` on the project root and tell the user to
   run `/reload-plugins`; skip to step 4.
3. **Run the updater of that copy** with the project root. Windows:
   `pwsh -NoProfile -File "<skill_root>/scripts/update-skill.ps1" -ProjectRoot "<project>" <translated arguments>`
   (`--check` → `-Check`, `--ref X` → `-Ref X`). Linux/macOS:
   `bash "<skill_root>/scripts/update-skill.sh" --project "<project>" <arguments>`. The script detects how the copy
   was installed (git checkout, Agent Skills CLI copy, plain copy), updates it, prints the changelog entries
   between the old and the new version, and re-runs `init-project` and `validate-project`.
4. **Report** in at most 15 lines: old → new version, what changed (from the printed changelog), the init and
   validate results, and the **Migration** steps that still need the CTO (config keys to add, the operating
   profile decision, lint findings to fix). Do not edit the project's config or vault yourself unless the user
   asks; the migration notes are decisions, not chores.
