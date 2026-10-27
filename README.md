# Qwen in Claude Code, via ModelScope

A take-home setup for **Agentic Builders Collective #11** by Jensen Loke.
Keep Claude Code as the coding harness and use a Qwen model served by ModelScope.

**[Five-minute talk](https://jensenloke.github.io/talks/abc11-claude-qwen/)** ·
**[ModelScope access registration](https://docs.google.com/forms/d/e/1FAIpQLSf_O5RR-HOCSwqS2BqYkVdwjd_95HQvyku63GtFPmyEGp-r-A/viewform?usp=dialog)**

The registration form offers 1,000 grains per participant and asks for your
ModelScope user ID and Luma registration email. It states a submission deadline
of **2 November 2026, 23:59** (timezone is not specified in the form).
Your API key stays on your computer; the form needs no API key.

Sharing the setup at a meetup? Download the **[repository QR (SVG)](assets/repository-qr.svg)**
or **[PNG](assets/repository-qr.png)**. It points to this public GitHub repository;
the registration form has its own separate QR in the talk.

## What is included

| Feature | How |
| --- | --- |
| Direct Qwen session | `claude-qwen` |
| Fixed-budget thinking + stream repair | `claude-qwen --thinking` |
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
- Choose the **exact model ID your account can access** from ModelScope's API
  model catalogue. Our tested example is `Qwen-Ambassador/Qwen3.8-Max`; access to
  that ambassador model is account-dependent. Registration is not an immediate
  API-access verification. Model IDs from DashScope/QwenCloud are not interchangeable.

The integration uses `https://api-inference.modelscope.ai/v1/messages`.
Windows users can try the launcher under WSL; Windows/WSL and Linux live-provider
behavior have not been validated here. Native Windows shell installation is not included.

## 2. Install the launcher and enter your key

```sh
git clone https://github.com/jensenloke/claude-qwen-modelscope.git
cd claude-qwen-modelscope
python3 qwen.py setup --model 'YOUR_MODELSCOPE_MODEL_ID'
```

Replace the model placeholder. Setup prompts for the key **without echoing it**.
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
claude-qwen doctor --live   # One small provider request; uses your ModelScope quota
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

### Context and thinking are separate

Setup defaults to a **200,000-token client window**. For a model/endpoint verified
to support 1M, rerun setup with `--context 1000000` and the same model/key options.
It sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS` to the window **minus each profile's
output cap** (direct: −8,192; thinking: −16,384), because the gateway rejects any
input longer than `window − max_tokens` — a 1M model with the 16,384 thinking
output cap hard-fails requests above 983,616 input tokens. Claiming the full
window leaves compaction starting after the gateway already refuses, and one
oversized request kills the session unrecoverably (`/compact` itself needs a
full-history call). Proactive compaction stays enabled and the upstream model
ID is unchanged. This tells Claude Code the expected window; it does not grant
provider capacity. No full million-token request has been used to validate the
limit. Restart after changing settings.

Direct mode explicitly disables thinking and caps output at 8,192 tokens.
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

## Why the thinking adapter exists

The tested ModelScope beta stream began a text block then emitted thinking deltas
inside it. Claude Code could end with an empty answer. `adapter.py` and
`protocol.py` repair that stream: separate text/thinking blocks, preserve provider
signatures without fabricating them, and serialize parallel tool fragments.
Malformed/truncated streams produce explicit errors.

Each thinking session runs an authenticated loopback server on a random port.
Claude receives a temporary token; the upstream key stays in the adapter.
The adapter ends with the foreground CLI, verifies upstream TLS, refuses redirects,
and bounds bodies, connections, buffers and timeouts. It does not retry billable
requests itself. Background/cloud/desktop launches are unsupported in this mode.
No daemon is installed. See the code and fixture tests for the exact bounds.

The thinking adapter also bounds images: any base64 image block above 120,000
characters (~90 KB binary) is replaced in flight with an explicit placeholder
telling the model to downscale first (e.g. `sips -Z 1024 -s format jpeg`).
One full-resolution phone screenshot can exceed 100K input tokens and stays in
the conversation history forever; a handful of them is enough to hit the input
cap above. The direct route has no adapter, so downscale images yourself there.

## Troubleshooting and removal

- **401/403:** check international endpoint, API key, model access and quota.
  Claude account login does not substitute for ModelScope credentials.
- **Unknown model/context warning:** use the exact ID and the documented custom
  context override; do not rename Qwen to a Claude model to hide the warning.
- **Blank thinking answer:** use `--thinking` and its adapter, not the direct
  route's thinking toggle. Recheck the provider stream if upstream behavior changes.
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
