# claude-skills

Global Claude Code setup: skills, hooks, global `CLAUDE.md`, and the PowerShell `cc` launcher.

## New machine

Requires PowerShell 7 (`pwsh`), Git with SSH access to this repo, and Python >= 3.12 (the hooks use only the standard library; session-colocate needs 3.12).

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

Changes to skills, the TL;NR and session-colocate hook scripts, the global `CLAUDE.md` and `cc` apply on pull. Changes to `setup/claude/commands`, `setup/claude/hooks` or `setup/settings.hooks.json` apply only after the installer runs again. It is idempotent and backs up every file it changes as `<file>.bak-<timestamp>`.

## How to set up / update on a new PC: plugins and MCP servers

`setup/plugins-mcp.json` lists the plugin marketplaces, the user-scope plugins (with their enabled state) and the user-scope MCP servers this setup expects. Step 6 of `install.ps1` runs `setup/plugins-mcp.ps1`, which makes the PC match it: missing marketplaces, plugins and MCP servers are added; ones the manifest does not list are uninstalled; matching ones are left alone. Any failing `claude` command stops the run.

```powershell
git clone git@github.com:bas1l/claude-skills.git $HOME\.claude\skills    # or: git -C $HOME\.claude\skills pull
pwsh -File $HOME\.claude\skills\setup\install.ps1                         # steps 1-6
pwsh -File $HOME\.claude\skills\setup\plugins-mcp.ps1 -DryRun             # only print the plugin/MCP plan
```

Then restart Claude Code. Asking Claude Code to "fetch the latest version of the skills repo" does the pull and the install itself (rule in `setup/claude/CLAUDE.md`).

**Environment variables.** No secret is stored in the manifest. Each `env` and `headers` value of an MCP server is written as `{{env:MCP_<SERVER>_<KEY>}}`, and the installer stops, naming every unset variable, before changing anything. Set them at user scope, e.g. `[Environment]::SetEnvironmentVariable('MCP_FOO_AUTHORIZATION', 'Bearer ...', 'User')`, then open a new terminal. The current manifest needs none: its only MCP server, `consensus`, signs in with OAuth on first use.

**Refreshing the manifest.** After installing or removing a plugin, marketplace or MCP server, run

```powershell
pwsh -File $HOME\.claude\skills\setup\plugins-mcp.ps1 -Mode Capture          # rewrite setup/plugins-mcp.json
pwsh -File $HOME\.claude\skills\setup\plugins-mcp.ps1 -Mode Capture -DryRun  # only check it is current (exit 1 if not)
```

review the diff and commit it. Capture stops if an MCP server's URL or arguments look like they carry a credential inline.

**What it does not manage.**

- claude.ai connectors (Gmail, Google Drive, Google Calendar, Canva, Claude Docs): account-level, nothing to install. They appear on any PC signed in to the account.
- Plugins and MCP servers at project or local scope: they belong to a repo (`.mcp.json`, `.claude/settings.json`), not the PC.
- `@builtin` plugins, shipped with Claude Code.
- Plugin option values (`claude plugin configure`); none are set today.
- The `claude-code-playground-mods` marketplace is a local folder. If it is missing, the installer clones `https://github.com/anthropics/claude-code-playground` to `~/claude-mods/claude-code-playground` first, which needs read access to that repo.

## Layout

| Path | What | How it reaches Claude Code |
|---|---|---|
| `<skill>/SKILL.md` | Global skills | Directly: this repo *is* `~/.claude/skills` |
| `hooks/tldr-gate/` | TL;NR summary rules (UserPromptSubmit), log-only check (Stop), and a summary added on screen when a long reply has none (MessageDisplay) | Referenced in place by `settings.json` |
| `hooks/session-colocate/` | SessionStart hook: moves the session's `%TEMP%` dir (scratchpad, tasks) next to its transcript and leaves a junction ([README](hooks/session-colocate/README.md)) | Referenced in place by `settings.json` |
| `hooks/upkeep_status/` | SessionStart hook: one warning line when an upkeep run failed | Referenced in place by `settings.json` |
| `upkeep/`, `upkeep-review/` | Scheduled upkeep of this setup ([README](upkeep/README.md)) | Tasks registered only with `install.ps1 -RegisterUpkeep` |
| `setup/claude/CLAUDE.md` | Global instructions | `~/.claude/CLAUDE.md` is a one-line `@import` of it |
| `setup/claude/guidance/` | Guidance read on demand ([which Claude Code feature for which purpose](setup/claude/guidance/claude-code-features.md)) | Pointer in `setup/claude/CLAUDE.md`, read in place |
| `setup/claude/commands/` | Slash commands (`/polish`) | Copied to `~/.claude/commands/` |
| `setup/claude/hooks/` | Brainstorm SessionStart nudge, speak / on-stop scripts | Copied to `~/.claude/hooks/` (their state flags live there) |
| `setup/settings.hooks.json` | Hook registrations and `cleanupPeriodDays` | Merged into `~/.claude/settings.json`, which keeps its other keys; the events and top-level keys listed in the template are replaced |
| `setup/plugins-mcp.json` | Marketplaces, user-scope plugins and MCP servers | Reconciled by `setup/plugins-mcp.ps1` (installer step 6), which also captures it |
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

## Public repository — no personal data

This repository is public. Never commit personal data. Git hooks (`.githooks/`, enabled by `setup/install.ps1` via `core.hooksPath`) and the `pii-guard` GitHub workflow both run `.githooks/pii-scan.sh` and block:

- real email addresses, except `*@users.noreply.github.com`, `noreply@github.com`, `noreply@anthropic.com`, `git@github.com` and `*@example.com/.org/.invalid`;
- absolute machine paths (`X:\...`, `X:/...`, `/Users/<name>`, `/home/<name>`), except `C:\Program Files*`, `C:\WINDOWS` and placeholders (`someone`, `x`, `<...>`); <!-- pii-allow -->
- the global git identity email (`git config --global user.email`) and any term listed one per line in `.githooks/denylist.local` (gitignored, case-insensitive, fixed strings; create it per machine, for example with your name);
- commits whose author or committer email is not a noreply address (use `git config user.email "<id>+<login>@users.noreply.github.com"` in this repo); the pre-push hook refuses them.

A deliberate, harmless line (a test fixture, a documented example) is exempted by putting `pii-allow` on it. Never use `--no-verify`; fix the content instead.
