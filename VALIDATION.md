# Verification — 26 October 2026

## Portable package, disposable home on macOS

- Python 3.15.0; 2.1.310 (Claude Code).
- Setup discovered the actual Claude executable, created both profiles, and stored credentials only in a temporary private home.
- 29 fixture tests passed: SSE repairs, tool fragment ordering, auth/origin/limits, deadline/cleanup behavior, executable discovery, isolated profile creation, key-file mode, credential scoping, and reconfiguration.
- Optional Brave MCP 2.1.4 and Chrome DevTools MCP 1.12.0 installed through the public commands; native Claude MCP checks reported both connected. DevTools verification stopped at process/tool registration and did not launch/control a browser.
- Both normal and thinking portable launches called Brave web search through MCP, returned official documentation URLs, and exited successfully.
- Normal mode emitted no thinking deltas; thinking mode emitted 14. Both reported contextWindow 1000000. That verifies the declared client window, not a full million-token provider request.
- Original private adapter integration had also passed live Read/Edit/final-answer exercises on two Macs. That historical check does not prove every packaged feature or third-party service.

## Limits of these checks

News search is configured but not separately live-tested. Browser automation itself, native Claude in Chrome login, Linux/WSL live-provider runs, and other account/model entitlements were not validated. Claude in Chrome is documented as unavailable to this ModelScope API-key session. No credentials, private profile snapshots, browser cookies or session transcripts are included.

The GitHub workflow runs fixture tests only, without provider secrets. Check its actual run before treating CI as passed.
