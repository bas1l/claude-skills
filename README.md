# claude-skills

Global Claude Code setup: skills, hooks, global `CLAUDE.md`, and the PowerShell `cc` launcher.

## New machine

Requires PowerShell 7 (`pwsh`), Git with SSH access to this repo, and any Python 3 (the hooks use only the standard library).

```powershell
git clone git@github.com:bas1l/claude-skills.git $HOME\.claude\skills
pwsh -File $HOME\.claude\skills\setup\install.ps1          # add -Python <path> to pick the interpreter
```

Then open a new terminal and restart Claude Code.

## Updating

```powershell
git -C $HOME\.claude\skills pull
pwsh -File $HOME\.claude\skills\setup\install.ps1          # only needed if setup/ changed
```

Changes to skills, the TL;NR hook scripts, the global `CLAUDE.md` and `cc` apply on pull. Changes to `setup/claude/commands`, `setup/claude/hooks` or `setup/settings.hooks.json` apply only after the installer runs again. It is idempotent and backs up every file it changes as `<file>.bak-<timestamp>`.

## Layout

| Path | What | How it reaches Claude Code |
|---|---|---|
| `<skill>/SKILL.md` | Global skills | Directly: this repo *is* `~/.claude/skills` |
| `hooks/tldr-gate/` | TL;NR summary gate (UserPromptSubmit + Stop hooks) | Referenced in place by `settings.json` |
| `setup/claude/CLAUDE.md` | Global instructions | `~/.claude/CLAUDE.md` is a one-line `@import` of it |
| `setup/claude/commands/` | Slash commands (`/polish`) | Copied to `~/.claude/commands/` |
| `setup/claude/hooks/` | Brainstorm SessionStart nudge, speak / on-stop scripts | Copied to `~/.claude/hooks/` (their state flags live there) |
| `setup/settings.hooks.json` | Hook registrations | Merged into `~/.claude/settings.json`, which keeps its other keys; the events listed in the template are replaced |
| `setup/pwsh/cc.ps1` | `cc` launcher | Dot-sourced from `$PROFILE` |
| `synced/` | Built-in skills that Claude Code syncs itself | Git-ignored |

Edit files in this repo, not the copies under `~/.claude`: the installer overwrites those copies (after backing them up).

## `cc` launcher

`cc [compound] [extra claude flags]`. The compound is any mix of these tokens, in any order and without spaces:

| Token | Meaning | Default |
|---|---|---|
| `2` | Account B (`CLAUDE_CONFIG_DIR=~/.claude-account-2`) | Account A |
| `o` / `h` / `s` | Opus / Haiku / Sonnet | Sonnet |
| `dsp` | `--dangerously-skip-permissions` | off |

```text
cc          Account A, Sonnet
cc o        Account A, Opus
cc dsp      Account A, Sonnet, skip permissions
cc dspo     Account A, Opus, skip permissions
cc 2hdsp    Account B, Haiku, skip permissions
cc dsp -c   Account A, Sonnet, skip permissions, continue the last session
```
