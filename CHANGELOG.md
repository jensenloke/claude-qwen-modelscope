# Release notes

## Unreleased — 2026-11-26

### Compaction recovery

- Preserve explicit no-tool requests when translating historical inline tool
  definitions, so compaction cannot accidentally restore executable tools.
- Separate user instructions from sibling tool results before forwarding to
  ModelScope. A live synthetic request reproduced an ignored trailing instruction
  and confirmed that separation restores it. Conversation files are not rewritten.
- Added regression coverage for empty tool catalogs, block order, image and
  tool-result preservation, and unchanged ordinary messages.

### Qwen 4 Max support

- `claude-qwen` now defaults to `Qwen-Ambassador/Qwen4-Max` on ModelScope.
- Setup upgrades the plain and thinking profiles and their model aliases,
  including subagents. It backs up replaced configuration and preserves existing
  skills, plugins, MCP registrations and conversation histories.
- Both launch modes now use the local compatibility adapter. Plain mode disables
  thinking while retaining stream repair, inline-tool translation and image
  bounds. Both modes keep the upstream key out of the Claude child process.
- Added `claude-qwen doctor --live --thinking` to verify thinking mode separately.
- Updated the installation and Qwen 3.8 upgrade instructions and removed the
  expired meetup registration offer. There is no automatic Qwen 3.8 fallback.

### Verification

- 43 fixture tests pass locally and in GitHub Actions on Python 3.10, 3.11 and 3.13.
- Live Qwen 4 checks passed on macOS with Claude Code 2.1.332: connection checks,
  Read → Edit → Read and session resume in both launch modes.
- A raw API image check passed, but the native Claude Read-image attempt did not
  complete during validation. Screenshot/browser image workflows and full-1M
  requests remain unqualified. See [validation details](VALIDATION.md).

Upgrade steps are in the [setup guide](README.md#upgrade-an-existing-qwen-38-installation).
Implementation: [PR #3](https://github.com/jensenloke/claude-qwen-modelscope/pull/3).
This entry records the pending update; no version tag or GitHub Release has been
published yet.
