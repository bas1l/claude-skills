---
name: vscode-click-to-open
description: Install, activate, deactivate or check the VS Code click-to-open hotkey, the AutoHotkey script (open-selection-click.ahk in the folder named by AHK_SCRIPTS_DIR) that makes Ctrl+Alt+Left-click in the VS Code terminal open the selected file path in its default external Windows app. USE THIS SKILL whenever the user asks in plain language to start, install, enable, stop, disable, turn on, turn off or check this hotkey, in any wording that mentions VS Code or the terminal together with click, open or external software, such as "start click vscode external software", "start vscode click to open", "enable click to open in vscode", "turn on ctrl alt click", "open files externally from vscode on click", "stop vscode click to open", "disable the click-to-open hotkey", "is vscode click to open active", "install open selection click". Activation persists across reboots, and so does deactivation.
argument-hint: "[install|activate|deactivate|status] (default: status)"
---

# vscode-click-to-open: install and switch the hotkey on or off

Controls `open-selection-click.ahk` in the folder named by the `AHK_SCRIPTS_DIR` environment variable through the helper at
`$HOME\.claude\skills\vscode-click-to-open\scripts\vscode-click-to-open.ps1`.

Active means both of these hold: the script is running now, and a shortcut in the
Windows Startup folder starts it at every logon. Deactivating removes both, so the
hotkey stays off after a reboot until it is activated again. Installing and activating
are the same operation, and repeating it changes nothing.

## Argument parsing: $ARGUMENTS

Map `$ARGUMENTS` to one action. When the skill is triggered by plain language,
`$ARGUMENTS` may be empty or the user's whole sentence, so read the intent from it.

| Argument or phrasing | Action |
|----------------------|--------|
| `install`, `activate`, `enable`, `on`, or any "install / turn on / enable" phrasing | `activate` |
| `deactivate`, `disable`, `off`, `uninstall`, `stop`, or any "turn off / disable / stop" phrasing | `deactivate` |
| *(empty)*, `status`, `check`, or "is it active" phrasing | `status` |

An empty argument never changes anything: it reports the state.

## Execution

Run exactly one command with the PowerShell tool, substituting the action:

```
& "$HOME\.claude\skills\vscode-click-to-open\scripts\vscode-click-to-open.ps1" -Action <action>
```

Do not launch `AutoHotkey64.exe` directly from Bash or with a bare `Start-Process`: a
process started that way is a child of the session shell and can end with the conversation.

## Response

The helper prints one line, for example
`ACTIVE running=true pid=1234 autostart=true extension=true`. Reply with a single line:

- `ACTIVE`: `VSCode-click-to-open is active (pid <n>) and starts at logon.`
- `INACTIVE`: `VSCode-click-to-open is off and will not start at logon. Say "start vscode click to open" to install it.`
- `PARTIAL`: state which of the two is missing (the running process or the Startup shortcut), and that `activate` or `deactivate` brings them back in line.

Add `The VS Code extension is missing, so the hotkey would do nothing.` when the line
has `extension=false`.

If the helper throws (AutoHotkey v2 missing, the `.ahk` file moved, the extension missing),
report the error message verbatim and do not retry with another launch method.

## What the script does (for context when the user asks)

- In VS Code only, Ctrl+Alt+Left-click sends Ctrl+Alt+O and swallows the click, so a terminal
  selection made by double-click stays intact.
- Ctrl+Alt+O is `openExternalLinks.openSelection` from the local VS Code extension
  `basil.open-external-links`, bound only while the terminal has focus. It opens the selected
  file path in its default Windows app.
- This helper checks that the extension folder exists. It does not install the extension and
  cannot tell whether the extension is disabled inside VS Code.
