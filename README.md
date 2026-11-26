# Qwen 4 Max in Claude Code, via ModelScope

Use Claude Code as the coding harness with **Qwen 4 Max** served by ModelScope.
The `claude-qwen` command now defaults to `Qwen-Ambassador/Qwen4-Max`.
Both plain and thinking modes use the compatibility adapter for stream repair,
inline tool changes and image bounds.

See the [release notes](CHANGELOG.md) for changes and verification details.

You need a [ModelScope international account](https://www.modelscope.ai/) with
inference access to the [Qwen Ambassador model](https://www.modelscope.ai/organization/Qwen-Ambassador?tab=model).
A model appearing in the catalogue does not by itself establish your account's
inference access. ModelScope keys and Alibaba Model Studio keys are different.

Originally shared at Agentic Builders Collective #11. The
[five-minute talk](https://jensenloke.github.io/talks/abc11-claude-qwen/) covers the
earlier setup; follow this README for the current Qwen 4 instructions. The old
meetup registration offer has ended.

Sharing the setup? Download the **[repository QR (SVG)](assets/repository-qr.svg)**
or **[PNG](assets/repository-qr.png)**. Both point to this public repository.

## What is included

| Feature | How |
| --- | --- |
| Plain Qwen 4 session | `claude-qwen` |
| Fixed-budget thinking | `claude-qwen --thinking` |
| Brave web/news search | Optional `add-brave` command; bring your own Brave key |
| Browser automation and debugging | Optional `add-devtools`; separate Chrome profile |
| Claude in Chrome extension | [Separate Anthropic-account instructions](docs/browser.md); unavailable in ModelScope API-key sessions |

This is a community compatibility setup, not an official Claude Code provider
integration. ModelScope credentials, model access and usage charges are separate
from an Anthropic subscription. Endpoint/model availability can change.

## 1. Prerequisites

- macOS or Linux, Python **3.10+**, Git, and an existing
  [Claude Code installation](https://code.claude.com/docs/en/setup).
- A [ModelScope international account](https://www.modelscope.ai/).
  Generate an API key in your [account settings](https://www.modelscope.ai/my/settings/account).
- Inference access to **`Qwen-Ambassador/Qwen4-Max`**. Verify it using the live
  doctor command below. Model IDs from Alibaba Model Studio/QwenCloud are not
  interchangeable with ModelScope model IDs.

The integration uses `https://api-inference.modelscope.ai/v1/messages`.
Windows users can try the launcher under WSL; Windows/WSL and Linux live-provider
behavior have not been validated here. Native Windows shell installation is not included.

## 2. Install the launcher and enter your key

```sh
git clone https://github.com/jensenloke/claude-qwen-modelscope.git
cd claude-qwen-modelscope
python3 qwen.py setup --context 1000000
```

Setup selects Qwen 4 Max and prompts for the key **without echoing it**.
For another supported model, pass its exact ID with `--model YOUR_MODEL_ID`.
It discovers `claude` on PATH; use `--claude /absolute/path/to/claude` if necessary.
To use an existing key file, add `--key-file /path/to/protected-file`.
The managed key is stored at `~/.config/claude-qwen/modelscope-api-key` with mode 600.

Setup creates two independent profiles, `~/.claude-qwen` and
`~/.claude-qwen-thinking`, plus a launcher symlink in `~/.local/bin`.
It does not import your main Claude settings, account identity, history, plugins,
MCP credentials or permissions. Existing Qwen settings are backed up and merged;
a different existing launcher requires an explicit `--replace-launcher`.
Backups are private files under `~/.config/claude-qwen/backups/` and may contain
credentials if you replaced an existing key. Keep them private too.

Keep this checkout in place: the installed launcher points here. Add the following
to `~/.zshrc` (or `~/.bashrc`), then open a new shell:

```sh
alias claude-qwen="$HOME/.local/bin/claude-qwen"
```

Alternatively add `~/.local/bin` to PATH. Setup does not edit shell startup files.
Setups on a Mac Mini work the same way after SSH login; run installation there
with its own Python/Claude paths. Share credentials only through your chosen
secure provisioning channel, never through a public repo or chat transcript.

## 3. Verify, then use it

```sh
claude-qwen doctor          # Local files/executable only; does not print keys
claude-qwen doctor --live   # One small plain-mode request; uses your ModelScope quota
claude-qwen doctor --live --thinking  # Separately check thinking mode
claude-qwen
claude-qwen --thinking
```

Put `--thinking` first. Remaining arguments go to Claude Code:

```sh
claude-qwen --thinking -p 'Explain the README in this directory.'
```

Your usual `claude` command stays separate. Histories and MCP logins belong to
their selected profile. Use ordinary Claude permissions; setup does not enable
bypass/auto-approval. Add your own skills/MCPs deliberately after the first test.

### Upgrade an existing Qwen 3.8 installation

From this checkout, update the source and rerun setup with your existing managed
key. This changes `claude-qwen` to Qwen 4 Max in both profiles:

```sh
git pull --ff-only
python3 qwen.py setup --context 1000000 \
  --key-file "$HOME/.config/claude-qwen/modelscope-api-key" \
  --replace-launcher
claude-qwen doctor --live
claude-qwen doctor --live --thinking
```

If your key is stored elsewhere, use that protected file instead. Setup backs up
changed settings and the launcher, updates the model aliases including subagents,
and preserves existing skills, plugins, MCP registrations and histories. It does
not copy customizations from a different Claude profile. Stop old sessions before
upgrading, then start a new session; old transcripts remain available, but resume
behavior depends on the gateway's support for their saved tool/thinking blocks.
An old Qwen 3.8 session does not automatically switch its active model when files
change. There is no automatic fallback to Qwen 3.8.

### Context and thinking are separate

Setup defaults to a **200,000-token client window**. For a model/endpoint verified
to support 1M, rerun setup with `--context 1000000` and the same model/key options.
It sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS` to the window **minus each profile's
output cap** (plain: −8,192; thinking: −16,384). This keeps an output reserve
before proactive compaction: at a 1M configured window, the thinking profile's
client input budget is 983,616. Earlier Qwen 3.8 gateway requests failed above
that input length. The reserve is retained for Qwen 4, but a full million-token
request and the exact Qwen 4 gateway boundary have not been tested. The upstream
model ID is unchanged; a client setting does not grant provider capacity.
Restart after changing settings.

Plain mode explicitly disables thinking and caps output at 8,192 tokens.
Thinking mode has a 4,096-token budget and 16,384-token output cap:

```sh
CLAUDE_QWEN_THINKING_BUDGET=8192 claude-qwen --thinking
```

Accepted budgets: 1,024–15,360. Claude's displayed effort preference is not the
switch for this fixed-budget mode.

## 4. Optional: Brave search

Install a current Node.js LTS release (22.12+ or 24 LTS recommended), including npm.
Create your own key at the [Brave Search API dashboard](https://api-dashboard.search.brave.com/).
Brave usage has its own quota/billing, separate from ModelScope grains.

```sh
claude-qwen add-brave
# Or: claude-qwen add-brave --key-file /path/to/existing/brave-key
```

The hidden prompt writes a mode-600 key file. The command installs Brave's
official MCP package, pinned to 2.1.4, and merges a stdio server into both Qwen
profiles. It exposes `brave_web_search` and `brave_news_search`; configuration
contains the `BRAVE_API_KEY_FILE` path, not the key itself. Search instructions
are added to each Qwen profile's `CLAUDE.md`. No main-profile configuration changes.

Restart, open `/mcp`, and ask: **“Use brave_web_search once to find the official
Brave Search API documentation and cite its URL.”** Confirm an actual tool call.
Approvals remain under your normal permission rules. ModelScope does not supply
Anthropic's native WebSearch service through this setup.

## 5. Optional: browser tools

```sh
claude-qwen add-devtools
```

Requires Node/npm and an installed Google Chrome. This pins the official
`chrome-devtools-mcp` package to 1.12.0 and configures both Qwen profiles to use a
temporary, isolated Chrome profile. It does not attach to your existing logged-in
browser. Usage statistics and CrUX performance lookups are disabled by the flags
in this setup. MCP connection alone does not start a browser.

Restart and check `/mcp`, then ask it to open your local demo and inspect the
console. Browser tools can read and act on pages; keep normal per-action permissions.
See **[browser setup and Claude in Chrome limitations](docs/browser.md)**.

## Why both modes use the adapter

The tested ModelScope beta stream began a text block then emitted thinking deltas
inside it. Claude Code could end with an empty answer. `adapter.py` and
`protocol.py` repair that stream: separate text/thinking blocks, preserve provider
signatures without fabricating them, and serialize parallel tool fragments.
Malformed/truncated streams produce explicit errors.

Each session runs an authenticated loopback server on a random port.
Claude receives a temporary token; the upstream key stays in the adapter.
The adapter ends with the foreground CLI, verifies upstream TLS, refuses redirects,
and bounds bodies, connections, buffers and timeouts. It does not retry billable
requests itself. Background/cloud/desktop launches are unsupported in both modes.
No daemon is installed. See the code and fixture tests for the exact bounds.

The adapter bounds images in both modes: any base64 image block above 120,000
characters (~90 KB binary) is replaced in flight with an explicit placeholder
telling the model to downscale first (e.g. `sips -Z 1024 -s format jpeg`).
One full-resolution phone screenshot can exceed 100K input tokens and stays in
the conversation history forever; a handful of them is enough to hit the input
cap above. A small synthetic image passed a raw Qwen 4 API check, but a native
Claude Read-image attempt did not complete during validation. Screenshot/browser
image workflows still need a separate smoke test; keep screenshots small and
inspect actual tool results. Browser tool setup is separate from model access.

### Tool changes and API compatibility

New Claude Code releases can send message blocks that ModelScope's Anthropic
endpoint does not yet accept. In particular, `tool_addition` and `tool_removal`
system blocks can cause a persistent **422**: retrying resends the same block
from history, even if the latest user message is ordinary text.

The adapter translates these blocks into system text at the same
position and updates the effective top-level tool catalog. It resolves named
references, promotes inline client definitions, and withholds removed tools.
It preserves ordinary text, tool calls/results and saved transcripts. This
flattens historical tool visibility for the current request; it does not emulate
Anthropic's per-message tool visibility or cache layout. Unsupported inline
reference types and missing definitions return explicit local errors.

After updating this checkout, exit and restart the affected session. For an
existing thinking session, you can try:

```sh
claude-qwen --thinking --resume YOUR_SESSION_ID
```

Plain mode receives the same translation with thinking explicitly disabled.
Existing private installations that copied `adapter.py` rather than using this
repo's launcher must also update that deployed copy. See the
[compatibility checklist](docs/compatibility.md) before upgrading either side.

## Troubleshooting and removal

- **401/403:** check international endpoint, API key, model access and quota.
  Claude account login does not substitute for ModelScope credentials.
- **422 mentioning `tool_addition` or `tool_removal`:** update the
  adapter, then exit and restart Claude Code in the same mode. Repeated prompts or
  `/compact` still resend the incompatible history through an old adapter.
- **Unknown model/context warning:** use the exact ID and the documented custom
  context override; do not rename Qwen to a Claude model to hide the warning.
- **Blank thinking answer:** start with `claude-qwen --thinking` so the adapter
  selects the fixed-budget mode. Recheck the provider stream if upstream behavior changes.
- **Compaction says “summarization produced empty response”:** update this checkout
  and restart using `claude-qwen --thinking --resume SESSION_ID` (omit `--thinking`
  for a plain-mode session). Run `/compact` again. The adapter keeps summary
  instructions separate from preceding tool results and respects the compactor's
  empty tool catalog. Existing history is preserved; `/clear` discards active
  context and should not be the first recovery step.
- **MCP says Connected but a call fails:** check that service's key/quota, executable
  requirements and actual tool result; a handshake proves discovery only.
- **Moved checkout or Claude executable:** rerun setup from the new checkout and
  pass `--replace-launcher` if necessary. Review the private backup before rollback.
- **Remove launcher:** remove the `claude-qwen` alias and unlink
  `~/.local/bin/claude-qwen` after verifying it points to this checkout. Profile
  histories, credentials and backups remain; review them separately before removal.

## Tests and provenance

```sh
python3 -m unittest discover -s tests -v
```

Tests use disposable homes, fixture keys and local fake upstream servers.
No production secrets or personal profiles are included. The protocol adapter was
previously exercised with live ModelScope calls on macOS (Claude Code 2.1.296 and
2.1.308); the portable packaging has its own verification in [VALIDATION.md](VALIDATION.md).
Browser support is not equivalent to verified provider/feature parity.

Sources checked 26 October 2026:
[ModelScope docs](https://www.modelscope.ai/docs/home),
[Claude Code custom context](https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id),
[Brave official MCP](https://github.com/brave/brave-search-mcp-server),
[Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp),
[Claude in Chrome prerequisites](https://code.claude.com/docs/en/chrome#prerequisites).

MIT license. Issues and patches welcome; include versions and redacted errors,
never API keys, browser cookies or private session dumps.
