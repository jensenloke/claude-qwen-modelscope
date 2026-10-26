# Browser setup: two different integrations

## Qwen / ModelScope: Chrome DevTools MCP

```sh
claude-qwen add-devtools
claude-qwen --thinking
```

Restart the CLI after adding the server. `/mcp` should list `chrome-devtools`.
Ask: “Open my local demo URL, take a screenshot and report any console errors.”
Use a demo application you control and review actions before submitting forms,
uploading files or changing data.

The setup uses the official package 1.12.0, stdio, an explicit local Node executable,
and `--isolated --no-usage-statistics --no-performance-crux`. The browser profile
is temporary, without your everyday browser's logins. The server launches Chrome
only when a tool needs it; connection success alone does not validate browser control.
It is not an OS sandbox: browser tools and the model can still reach resources
their host/permissions permit.

The generated server entry lives in each Qwen profile's `.claude.json`.
Attaching to an existing browser through `--autoConnect` / a debugging URL is an
advanced upstream feature and is not enabled by this installer. Do not expose a
remote-debugging port on your network or copy a logged-in browser profile to share it.

## Regular Claude: Claude in Chrome extension

This is **not a working browser bridge for the ModelScope API-key profile**.
Anthropic's current docs require `/login` with a direct Pro, Max, Team or Enterprise
plan and keep Chrome integration off for API-key sessions, even with `--chrome`.
The thinking adapter does not bypass that account requirement.

To use it separately in your regular Claude session:

1. Follow the [official Chrome integration guide](https://code.claude.com/docs/en/chrome).
2. Install **Claude in Chrome** from the official Chrome Web Store link there;
   sign into your own eligible account. The docs require extension 1.0.36+.
3. In regular `claude`, use `/login` as needed, then start `claude --chrome`.
4. Use `/chrome` to inspect connectivity and manage site permissions.
5. Approve only the sites/actions you intend. That integration shares the selected
   browser's login state and uses your Anthropic account, not ModelScope grains.

Do not copy extension credentials, native messaging tokens or another user's
account state into a Qwen profile. The native extension bridge is managed by
Claude Code, not installed here as an arbitrary `claude-in-chrome` MCP entry.

Sources checked 26 October 2026:
[Anthropic prerequisites](https://code.claude.com/docs/en/chrome#prerequisites),
[DevTools configuration](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/configuration.md).
The DevTools registration can be checked without launching Chrome; an end-to-end
browser run is a separate check (see [validation](../VALIDATION.md)).
