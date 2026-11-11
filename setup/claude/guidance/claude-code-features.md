# Claude Code features: what to use for which purpose

Read this before adding or changing a Claude Code customisation (instruction, skill, hook, MCP server, plugin, setting).

**Status.** Written 2026-11-01. The variable names in section 4 come from the code.claude.com documentation as read that day (sources in section 6); they were not each tested by running them. The "use this for" choices in sections 1 and 2 are judgement built on those docs, not statements from them. Claude Code changes quickly, so check a variable against the docs before relying on it.

## 1. Choose by purpose

| You want | Use | Why this one |
|---|---|---|
| An instruction that applies to every task | `CLAUDE.md` | Always loaded at session start |
| An instruction for one topic or one file type | Rule with `paths:` | Loads only when matching files are touched, so context stays clean |
| Claude to remember a personal or machine-specific fact | Auto memory | Stays on this machine, outside git |
| A repeatable procedure, or reference knowledge used only sometimes | Skill | Only its description is listed until it is invoked |
| Work done in a separate context, keeping verbose output out of the main one | Subagent | Has its own context and returns only a result |
| Something that must happen every time | Hook | Claude Code runs it; Claude cannot forget it |
| Something that must never (or always may) happen | Permission rule, sandbox | Enforced by Claude Code, not by Claude's reading of an instruction |
| New tools, or access to an outside service | MCP server | Adds callable tools |
| To install or share several of the above as one unit | Plugin | A package; it can bundle all of the above |
| To change how answers are written, in every session | Output style | Changes the system prompt |
| To change the model, effort or cost limit | Settings, flags, environment variables | Section 4.1 and 4.8 |
| To run unattended or on a timer | `-p`, `/loop`, `/schedule` | Section 4.7 |

**The main test: guidance or guarantee?** `CLAUDE.md`, rules, memory and skills are text placed in context, so Claude can still fail to follow them. Hooks, permission rules and the sandbox are applied by Claude Code itself. If a failure would be costly, use the second kind. "From now on, whenever X" cannot be met by memory; it needs a hook.

## 2. Differences that are easy to confuse

### Memory vs rule vs `CLAUDE.md`

The docs group all three under "memory" in the broad sense.

| | `CLAUDE.md` | Rule | Auto memory |
|---|---|---|---|
| Written by | You | You | Claude, usually (you can edit it) |
| Content | Standing instructions | Standing instructions on one topic | What Claude learned: corrections, preferences, project facts |
| Form | One file per level, plus subfolders | Many small files in `.claude/rules/` | `MEMORY.md` index plus topic files |
| Loads | At session start; a subfolder's file only when Claude works there | At session start, or only for matching files if it has `paths:` | First 200 lines or 25 KB of `MEMORY.md` at session start |
| Shared by git | Yes, except `CLAUDE.local.md` | Yes, if the project rules are committed | No |
| All-projects location | `~/.claude/CLAUDE.md` | `~/.claude/rules/` | None; each git repo has its own |

A rule without `paths:` behaves much like a section of `CLAUDE.md` in its own file. The real gain comes from `paths:`.

Worked examples:
- "Fail fast, no silent fallbacks" applies to every task: `CLAUDE.md`.
- "Use ruamel.yaml only" matters only in Python code: rule with `paths: ["**/*.py"]`. Anyone cloning the repo gets it, and it loads without Claude having to decide to open a guidance file.
- "Keep total workers to about 12 of 16 cores" describes one machine: memory.

### Plugin vs MCP

Neither is the same as the other, and neither is strictly a subcategory.

- **MCP server:** a connection that gives Claude new tools, often to an outside service. MCP (Model Context Protocol) is an open standard, not specific to Claude Code.
- **Plugin:** a Claude Code install package that can bundle skills, subagents, hooks, MCP servers, output styles and more.

The relationship is optional containment. A plugin may contain no MCP server or several. An MCP server may run with no plugin, added with `claude mcp add` or through `.mcp.json`.

Worked examples seen on 2026-11-01:
- `consensus`: an MCP server giving a research-paper search tool.
- `skins`: a plugin giving both a skill (`skins:skin-designer`) and a tool (`mcp__skins__design`).
- `frontend-design`: appears as a skill only (`frontend-design:frontend-design`).

### Skill vs subagent vs hook

- **Skill:** instructions Claude loads when needed. They run in the current conversation unless the skill sets `context: fork`.
- **Subagent:** a separate worker with its own context, tools and model. A skill says how to do something; a subagent is who does it apart from the main conversation.
- **Hook:** a handler Claude Code runs on an event. It does not depend on Claude choosing to act.

Plain slash commands (plugin `commands/`, flat `.md`) still work, but the docs now prefer skills.

## 3. Where each thing goes in this repo (`bas1l/claude-skills`)

From `README.md`:

| Thing | Path | Reaches Claude Code by |
|---|---|---|
| Global skill | `<skill>/SKILL.md` | Directly; this repo is `~/.claude/skills` |
| Global instructions | `setup/claude/CLAUDE.md` | `~/.claude/CLAUDE.md` imports it |
| Guidance read on demand | `setup/claude/guidance/*.md` | Pointer in `setup/claude/CLAUDE.md` |
| Slash command | `setup/claude/commands/` | Copied by the installer |
| Hook script | `hooks/<name>/` or `setup/claude/hooks/` | Referenced in place, or copied by the installer |
| Hook registration | `setup/settings.hooks.json` | Merged by the installer |
| Plugin, marketplace, user-scope MCP server | `setup/plugins-mcp.json` | Reconciled by the installer; refresh with `setup/plugins-mcp.ps1 -Mode Capture` |

Project-scope items belong in the project repo, not here: `.claude/rules/`, `.claude/settings.json`, `.mcp.json`, `.claude/agents/`, `.claude/skills/`. Auto memory lives outside every repo, so it is not backed up by this one. The README layout lists no folder for global rules (`~/.claude/rules/`); add one there if global rules are ever used.

## 4. Inventory with variables

Notation: `camelCase` = key in `settings.json`; `UPPER_CASE` = environment variable; `--x` = command-line flag; `/x` = session command.

Settings precedence: managed > `--settings` > local (`.claude/settings.local.json`) > project (`.claude/settings.json`) > user (`~/.claude/settings.json`). List keys such as `permissions.allow` merge across files. `fallbackModel` and `modelPicker` do not merge.

### 4.1 LLM

**Model and version**
- Set: `/model`, `--model`, `ANTHROPIC_MODEL` (overrides the key), `model`; `ANTHROPIC_DEFAULT_MODEL` applies only when no settings file sets `model`
- Aliases: `default`, `best`, `fable`, `opus`, `sonnet`, `haiku`, `sonnet[1m]`, `opus[1m]`, `opusplan` (Opus in plan mode, Sonnet for execution)
- Exact version: full ID such as `claude-opus-5-5`
- Alias mapping: `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL` (with `_NAME`, `_DESCRIPTION`, `_SUPPORTED_CAPABILITIES`), `modelOverrides`
- Custom picker entry: `ANTHROPIC_CUSTOM_MODEL_OPTION`
- Picker limits: `availableModels`, `deniedModels`, `enforceAvailableModels`, `modelPicker`
- Fallback: `--fallback-model a,b` (up to 3), `fallbackModel`, `CLAUDE_CODE_DISABLE_MODEL_ACCESS_FALLBACK`, `CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK`
- Subagents: frontmatter `model`, `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`

**Thinking intensity**
- Effort values: `low`, `medium`, `high`, `xhigh`, `max`; `ultracode` only through `--effort`
- Set effort: `/effort`, `--effort`, `CLAUDE_CODE_EFFORT_LEVEL`, `effortLevel` (no `max`), `modelSettings` (per model), frontmatter `effort`
- Effort resolution: environment > in-session pick > `--effort` > settings > model default
- Cap and force: `maxEffortLevel`, `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT`
- Thinking: Alt+T, `alwaysThinkingEnabled`, `showThinkingSummaries`, `MAX_THINKING_TOKENS`, `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING` (Opus 4.6, Sonnet 4.6), `CLAUDE_CODE_DISABLE_THINKING`, `ultrathink` in a prompt (one turn)
- Limit: thinking cannot be disabled on Opus 5.5, Sonnet 5.5, Haiku 5.5 or Fable

**Speed, context, output**
- Fast mode (Opus 5.5, Opus 5, Opus 4.8): `/fast`, `fastMode`, `fastModePerSessionOptIn`, `CLAUDE_CODE_DISABLE_FAST_MODE`, `CLAUDE_CODE_SKIP_FAST_MODE_NETWORK_ERRORS`, `CLAUDE_CODE_SKIP_FAST_MODE_ORG_CHECK`
- Context window: `[1m]` suffix, `CLAUDE_CODE_DISABLE_1M_CONTEXT`, `CLAUDE_CODE_MAX_CONTEXT_TOKENS`
- Compaction: `/autocompact`, `--autocompact`, `autoCompactEnabled`, `autoCompactWindow`, `idleCompaction`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`
- Output length: `CLAUDE_CODE_MAX_OUTPUT_TOKENS`
- Prompt cache lifetime: `promptCacheTtl`, `subagentPromptCacheTtl`, subagent frontmatter `experimental.cacheTtl` (`5m`, `1h`)

**Provider and login**
- Anthropic: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `apiKeyHelper`, `forceLoginMethod`, `forceLoginOrgUUID`
- Vertex: `CLAUDE_CODE_USE_VERTEX`, `ANTHROPIC_VERTEX_PROJECT_ID`, `ANTHROPIC_VERTEX_BASE_URL`, `gcpAuthRefresh`
- Bedrock: `AWS_BEARER_TOKEN_BEDROCK`, `ANTHROPIC_BEDROCK_BASE_URL`, `ANTHROPIC_BEDROCK_REGION_PREFIX`, `awsAuthRefresh`, `awsCredentialExport`
- Foundry: `ANTHROPIC_FOUNDRY_RESOURCE`, `ANTHROPIC_FOUNDRY_API_KEY`, `ANTHROPIC_FOUNDRY_BASE_URL`, `ANTHROPIC_FOUNDRY_AUTH_TOKEN`

### 4.2 Instructions and memory

- `CLAUDE.md` levels: managed (Windows `C:\Program Files\ClaudeCode\CLAUDE.md`), `~/.claude/CLAUDE.md`, `./CLAUDE.md` or `./.claude/CLAUDE.md`, `./CLAUDE.local.md`, nested subfolders
- `CLAUDE.md` controls: `@path` imports (ignored inside backticks or code fences), `claudeMdExcludes`, `CLAUDE_CODE_DISABLE_CLAUDE_MDS`, `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD`
- Rules: `.claude/rules/**/*.md`, `~/.claude/rules/`, frontmatter `paths:`
- Auto memory: `~/.claude/projects/<project>/memory/`, `autoMemoryEnabled`, `autoMemoryDirectory`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY`
- Output styles: `/output-style`, `outputStyle`, `~/.claude/output-styles/*.md`, `.claude/output-styles/*.md`; built-ins `Default`, `Proactive`, `Concise`, `Explanatory`, `Learning`; frontmatter `name`, `description`, `keep-coding-instructions`, `force-for-plugin`
- System prompt: `--system-prompt[-file]` (replace), `--append-system-prompt[-file]` (append), `--system-prompt-snapshot off`, `--exclude-dynamic-system-prompt-sections`
- Inspect: `/memory`, `/init`, `/context`

### 4.3 Extensions

**Skills**
- Locations: `~/.claude/skills/<name>/SKILL.md`, `.claude/skills/<name>/SKILL.md`, plugin `skills/`, `--add-dir` directories, managed directory. Precedence: enterprise > personal > project; plugin skills are namespaced `/plugin:skill`
- Frontmatter: `name`, `description`, `when_to_use`, `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `disallowed-tools`, `model`, `effort`, `context` (`fork`), `agent`, `background`, `hooks`, `paths`, `shell` (`bash`, `powershell`), `metadata`
- Settings: `skillOverrides` (`on`, `name-only`, `user-invocable-only`, `off`), `disableBundledSkills`, `disableSkillShellExecution`, `skillListingBudgetFraction`, `skillListingMaxDescChars`
- Substitutions: `$ARGUMENTS`, `$ARGUMENTS[N]`, `$N`, `$name`, `${CLAUDE_SKILL_DIR}`, `${CLAUDE_SESSION_ID}`, `${CLAUDE_EFFORT}`, `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`
- Disable all skills and commands: `--disable-slash-commands`

**Subagents**
- Locations (high to low): managed `.claude/agents/`, `--agents '<json>'`, `.claude/agents/`, `~/.claude/agents/`, plugin `agents/`
- Frontmatter: `name` and `description` (required), `tools`, `disallowedTools`, `model` (`sonnet`, `opus`, `haiku`, `fable`, ID, `inherit`), `permissionMode`, `maxTurns`, `autoCompactWindow`, `skills`, `mcpServers`, `hooks`, `memory` (`user`, `project`, `local`), `background`, `omitClaudeMd`, `effort`, `isolation` (`worktree`), `color`, `initialPrompt`, `experimental`
- Built-ins: `Explore`, `Plan`, `general-purpose`, `statusline-setup`, `claude-code-guide`, `claude`
- Disable: `permissions.deny: ["Agent(Explore)"]`, `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS`, `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS`
- Limits: `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (default 20), `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` (default 3), `CLAUDE_CODE_FORK_SUBAGENT`
- Default session agent: `--agent`, `agent`

**MCP servers**
- Transports: `http` (recommended), `stdio`, `sse` (deprecated), `ws` (JSON only), `sdk`
- Scopes: `local` (default) and `user` in `~/.claude.json`; `project` in `.mcp.json`
- Manage: `claude mcp add --transport <t> --scope <s> --env K=V --header "H: v" <name>`, `claude mcp add-json|list|get|remove|login|logout`, `/mcp`, `--mcp-config`, `--strict-mcp-config`
- `.mcp.json` keys: `type`, `command`, `args`, `env`, `url`, `headers`, `headersHelper`, `timeout`, `alwaysLoad`, `oauth` (`clientId`, `callbackPort`, `authServerMetadataUrl`, `scopes`); `${VAR}` and `${VAR:-default}` expand in `command`, `args`, `env`, `url`, `headers`
- Limits: `MCP_TIMEOUT`, `MCP_TOOL_TIMEOUT`, `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` (default 5 min remote, 30 min stdio), `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS` (default 2 min), `MAX_MCP_OUTPUT_TOKENS` (default 25,000), `ENABLE_TOOL_SEARCH`, `MCP_DISCOVERY_CACHE`
- Allow or block: `allowedMcpServers`, `deniedMcpServers`, `enableAllProjectMcpServers`, `enabledMcpjsonServers`, `disabledMcpjsonServers`, `allowManagedMcpServersOnly`

**Hooks**
- Events (33): `SessionStart`, `Setup`, `SessionEnd`, `UserPromptSubmit`, `UserPromptExpansion`, `Stop`, `StopFailure`, `PreToolUse`, `PermissionRequest`, `PermissionDenied`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`, `TeammateIdle`, `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `DirectoryAdded`, `FileChanged`, `WorktreeCreate`, `WorktreeRemove`, `PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch`, `Notification`, `MessageDisplay`, `Elicitation`, `ElicitationResult`
- Handler types: `command`, `http`, `mcp_tool`, `prompt`, `agent` (experimental)
- Common keys: `type`, `if` (permission-rule syntax), `timeout`, `statusMessage`, `once` (skills only)
- Per handler: command `command`, `args`, `async`, `asyncRewake`, `shell`, `onFailure`; http `url`, `headers`, `allowedEnvVars`; mcp_tool `server`, `tool`, `input`; prompt and agent `prompt`, `model`
- Matcher: `"*"`, exact name, `a|b`, or regex; some events ignore matchers
- Exit codes: 0 = success (JSON stdout parsed); 2 = block on events that can block (stderr goes to Claude); other = non-blocking error
- Locations: settings `hooks` at any level, plugin `hooks/hooks.json`, skill or subagent `hooks:`
- Settings: `disableAllHooks`, `allowManagedHooksOnly`, `allowedHttpHookUrls`, `httpHookAllowedEnvVars`

**Plugins and marketplaces**
- Manifest `.claude-plugin/plugin.json`: `name` (required), `version`, `skills`, `commands`, `agents`, `hooks`, `mcpServers`, `lspServers`, `outputStyles`, `workflows`, `userConfig`, `channels`, `dependencies`, `defaultEnabled`, `settings`
- Default folders: `skills/`, `commands/`, `agents/`, `hooks/hooks.json`, `.mcp.json`, `.lsp.json`, `output-styles/`, `workflows/`, `monitors/monitors.json`, `bin/`, `settings.json`
- Settings: `enabledPlugins`, `extraKnownMarketplaces`, `strictKnownMarketplaces`, `blockedMarketplaces`, `pluginConfigs`, `prependPlugins`, `appendPlugins`
- Options: `${user_config.KEY}`, `CLAUDE_PLUGIN_OPTION_<KEY>` in hooks
- One session only: `--plugin-dir`, `--plugin-url`

**Agent teams and workflows**
- Teams: `--teammate-mode in-process|auto|tmux|iterm2`, `teammateMode`
- Workflows: `enableWorkflows`, `disableWorkflows`, `workflowKeywordTriggerEnabled`, `workflowSizeGuideline`, `CLAUDE_CODE_DISABLE_WORKFLOWS`, plugin `workflows/`

### 4.4 Permissions and safety

- Modes: `default` (alias `manual`), `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions`. `auto` and `bypassPermissions` are ignored from project and local settings
- Set mode: `--permission-mode`, `permissions.defaultMode`, Shift+Tab, `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`
- Rules: `permissions.allow|ask|deny`, e.g. `Bash(npm run test *)`, `Read(./.env)`, `Agent(Explore)`, `mcp__<server>__<tool>`
- Tool lists: `--tools`, `--allowedTools`, `--disallowedTools`, subagent `tools` and `disallowedTools`
- Folders: `--add-dir`, `permissions.additionalDirectories`, `permissions.blockReadsOutsideWorkingDirectories`
- Other: `permissions.disableBypassPermissionsMode`, `disableAutoMode`, `allowManagedPermissionRulesOnly`, `skipDangerousModePermissionPrompt`, `autoMode`, `autoMode.classifyAllShell`, `useAutoModeDuringPlan`, `--permission-prompt-tool`, `--permission-prompts none`
- Sandbox (off by default): `/sandbox`, `sandbox.enabled`, `sandbox.filesystem.allowWrite|denyWrite|allowRead|denyRead`, `sandbox.network.allowedDomains|deniedDomains|strictAllowlist|httpProxyPort|socksProxyPort`, `sandbox.excludedCommands`, `sandbox.failIfUnavailable`, `sandbox.allowUnsandboxedCommands`, `sandbox.autoAllowBashIfSandboxed`, `sandbox.credentials.*`
- Windows limit: native Windows runs unsandboxed; sandboxing needs WSL2 (`bubblewrap`, `socat`)

### 4.5 Execution

- Bash: `BASH_DEFAULT_TIMEOUT_MS`, `BASH_MAX_TIMEOUT_MS`, `BASH_MAX_OUTPUT_LENGTH`, `bashOutputMaxChars`
- Shell: `defaultShell` (`bash`, `powershell`), `CLAUDE_CODE_GIT_BASH_PATH`, `CLAUDE_CODE_DISABLE_WINDOWS_SHELL_LAUNCHER`
- Background: `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`, `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`
- Worktrees: `--worktree`, `--tmux`, `worktree.baseRef`, `worktree.bgIsolation`, `worktree.sparsePaths`, `worktree.symlinkDirectories`
- Files and web: `respectGitignore`, `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`, `CLAUDE_CODE_GLOB_HIDDEN`, `CLAUDE_CODE_GLOB_NO_IGNORE`, `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION`, `CLAUDE_CODE_DISABLE_WEB_FETCH`

### 4.6 Interface

- Theme: `theme`, `/config`, plugin `themes/` (experimental)
- Status line: `statusLine` (`type`, `command`, `padding`, `refreshInterval`), `/statusline`
- Keybindings: `~/.claude/keybindings.json`, `/keybindings`
- Vim mode: `editorMode`, `vimInsertModeRemaps`
- Voice: `/voice [hold|tap|off]`, `voice` (`enabled`, `mode`, `autoSubmit`), `language`
- Notifications: `preferredNotifChannel`, `inputNeededNotifEnabled`, `agentPushNotifEnabled`
- Spinner: `spinnerVerbs`, `spinnerTipsEnabled`, `spinnerTipsOverride`
- Display: `tui`, `viewMode`, `verbose`, `showTurnDuration`, `prefersReducedMotion`, `syntaxHighlightingDisabled`, `maxProseWidth`, `timeFormat`, `timeZone`, `terminalTitleFromRename`, `CLAUDE_CODE_DISABLE_TERMINAL_TITLE`, `CLAUDE_CODE_NO_FLICKER`, `CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN`, `--ax-screen-reader`

### 4.7 Automation

- Non-interactive: `-p`, `--output-format text|json|stream-json`, `--input-format text|stream-json`, `--json-schema`, `--include-partial-messages`, `--include-hook-events`, `--forward-subagent-text`, `--bare`, `--permission-prompts none`
- Sessions: `--continue`, `--resume`, `--name`, `--fork-session`, `--session-id`, `--no-session-persistence`, `CLAUDE_CODE_SKIP_PROMPT_HISTORY`
- Background and remote: `--bg`, `--exec`, `claude agents`, `--remote-control`, `--cloud`, `--environment`, `--teleport`
- Scheduling: `/loop 5m <prompt>` (fixed), `/loop <prompt>` (self-paced), `.claude/loop.md`, `~/.claude/loop.md`, `CLAUDE_CODE_DISABLE_CRON`, `/schedule` (cloud, minimum 1 hour). Recurring session tasks expire after 7 days
- Agent SDK: `claude-agent-sdk` (Python), `@anthropic-ai/claude-agent-sdk` (TypeScript)

### 4.8 Cost, monitoring, debugging

- Limits: `--max-budget-usd` (print mode; client-side estimate; includes subagents), `--max-turns`, `CLAUDE_CODE_MAX_TURNS`
- Spend: `modelPricing`, `total_cost_usd` in JSON output, `cost.total_cost_usd` in the status line, `/usage`
- Telemetry: `CLAUDE_CODE_ENABLE_TELEMETRY`, `OTEL_METRICS_EXPORTER`, `OTEL_LOGS_EXPORTER`, `OTEL_TRACES_EXPORTER`, `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_METRIC_EXPORT_INTERVAL`, `OTEL_LOGS_EXPORT_INTERVAL`, `OTEL_RESOURCE_ATTRIBUTES`
- Telemetry content (off by default): `OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_TOOL_DETAILS`, `OTEL_LOG_TOOL_CONTENT`, `OTEL_LOG_RAW_API_BODIES`
- Opt-outs: `DISABLE_TELEMETRY`, `DISABLE_ERROR_REPORTING`, `DO_NOT_TRACK`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, `CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY`
- Debugging: `--debug`, `--debug-file`, `CLAUDE_CODE_DEBUG_LOGS_DIR`, `CLAUDE_CODE_DEBUG_LOG_LEVEL`, `--safe-mode`, `/status`, `/doctor`

### 4.9 Config locations

- `~/.claude/settings.json`: user settings
- `~/.claude.json`: user and local MCP servers, trust decisions, `/config` globals
- `CLAUDE_CONFIG_DIR`: moves `~/.claude` (the `cc` launcher uses it for account B)
- `--settings <file|json>`: override for one session
- `--setting-sources user,project,local`: choose which files load

## 5. Known gaps

- This inventory is not exhaustive. The environment-variable and settings reference pages are longer than this list.
- Pages not read: `github-actions`, `agent-teams`, `workflows`, `interactive-mode`, `checkpointing`. Those areas are thin here.
- Not confirmed in the docs read: the Bedrock and Foundry on/off variables, a variable to disable prompt caching, the allowed values of `editorMode`, the exact meaning of each workflow setting.

## 6. Sources

Index: https://code.claude.com/docs/llms.txt. Pages, all under `https://code.claude.com/docs/en/`: `settings`, `settings-reference`, `cli-reference`, `env-vars`, `model-config`, `fast-mode`, `memory`, `output-styles`, `skills`, `sub-agents`, `mcp`, `plugins/manifest-reference`, `hooks`, `permissions`, `permission-modes`, `sandboxing`, `statusline`, `keybindings`, `voice-dictation`, `scheduled-tasks`, `headless`, `monitoring-usage`.

To refresh: ask the `claude-code-guide` agent to re-check these pages and the gaps in section 5, then update this file and its date.
