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

## Context-clamp and image-budget verification — 27 October 2026

- Trigger: a live thinking session (Qwen3.8-Max, 1M client window) died with gateway
  `400 InternalError.Algo.InvalidParameter: Range of input length should be [1, 983616]`
  after six base64 screenshots (~1.65M chars) accumulated in history; the session was
  unrecoverable because `/compact` also requires a full-history request.
- Fix 1: setup now writes `CLAUDE_CODE_MAX_CONTEXT_TOKENS = window − profile output cap`
  (983,616 / 991,808 at `--context 1000000`) so compaction triggers before the gateway cap.
- Fix 2: the thinking adapter elides base64 image blocks over 120,000 chars into an explicit
  downscale-instruction placeholder before forwarding upstream.
- 31 fixture tests passed on macOS (Python 3.15.0), including the two new image-budget tests
  and the updated setup clamp assertion. No live provider request was used.

## Inline tool changes — 28 October 2026

- Trigger: Claude Code sent a system notice containing named `tool_addition`
  blocks. ModelScope rejected the block union with 422. Retries retained the
  incompatible block in history.
- A minimal synthetic request reproduced the provider's 422. The same request
  through the deployed translation returned HTTP 200 with a message response.
- On the Mac Mini (Python 3.14.7), the original affected notice and its two tool
  definitions also returned HTTP 200 through the patched adapter. The private
  transcript was not edited or added to this repo. This was a reduced request,
  not a replay of the entire conversation or a resumed interactive session.
- The portable suite passes 39 fixture tests on macOS (Python 3.15.0), including
  eight inline-tool cases: a late system notice, definitions/removal/readdition,
  unchanged ordinary history, token counting, unresolved references, malformed
  or unsupported descriptors, schema replacement, and preservation of unrelated
  blocks. Fixtures use no provider credentials.
- CI now includes the minimum supported Python 3.10 as well as 3.11/3.13, and
  permits manual workflow runs. Its result must be checked separately.
- Scope: thinking-mode adapter only. Translation flattens current tool
  availability; Anthropic's historical visibility/cache semantics, arbitrary
  future block types and direct-mode feature parity are not established.
