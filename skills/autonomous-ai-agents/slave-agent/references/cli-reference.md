# slave-agent CLI Reference

Live sources when anything looks stale: `slave --help`, `slave <command> --help`,
https://hermes-agent.nousresearch.com/docs/reference/cli-commands

### Global Flags

```
slave [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
slave chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
slave setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
slave model                Interactive model/provider picker
slave fallback [add|remove|list]  Fallback provider chain
slave config [show|edit|get|set|unset|path|env-path|check|migrate]
slave login / logout       OAuth sign-in / clear stored auth
slave doctor [--fix]       Check dependencies and config
slave status [--full]      Component summary (--full: every section)
```

### Tools & Skills

```
slave tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

slave skills list|browse|search QUERY|inspect ID
slave skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
slave skills config        Enable/disable skills per platform
slave skills check|update|uninstall|publish PATH
slave skills tap add REPO  Add a GitHub repo as a skill source
slave bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
slave mcp add NAME (--url or --command) | remove | list | test NAME
slave mcp catalog | install NAME     Curated catalog install
slave mcp configure NAME             Toggle tool selection
slave mcp serve                      Run slave-agent as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
slave gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `slave photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
slave sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
slave cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
slave webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
slave profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
slave profile rename A B | alias NAME | export NAME | import FILE
slave profile migrate-identity A B   Retry a completed rename's session/routing identity migration
```

### Credentials & Pools

```
slave auth                 Interactive credential manager
slave auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
slave auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
slave desktop / gui        Native desktop app
slave dashboard            Web admin panel + embedded chat (--stop / --status)
slave proxy                OpenAI-compatible local proxy backed by an OAuth provider
slave portal               Quick setup / sign in via Nous Portal
slave kanban <verb>        Multi-agent work-queue board
slave project              Named multi-folder workspaces
slave skin list|use|set    Switch/tweak skins (see references/themes.md)
slave pets <verb>          Pet mascots (see references/petdex.md)
slave memory setup|status|off|reset   Memory provider
slave secrets bitwarden|onepassword   External secret stores
slave moa                  Mixture-of-Agents slots
slave hooks / security / backup / import / checkpoints / console
slave logs [-f] [errors]   View agent/error logs
slave send                 One-off message through a gateway platform
slave pairing / plugins / insights / journey / computer-use
slave acp                  ACP server (IDE integration)
slave completion bash|zsh|fish
slave update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `slave photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `slave config edit` · [Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| Tools / toolsets | `slave tools list` · [Tools reference](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| Skills catalog | `slave skills browse` · [Skills catalog](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `slave model` · [Providers guide](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| Env variables | `slave config env-path` · [Env vars reference](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| Gateway logs | `~/.slave/logs/gateway.log` (or `slave logs`) |
| Sessions | `slave sessions browse` (reads state.db) |
