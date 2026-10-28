# Watching Claude Code / ModelScope compatibility

Claude Code and ModelScope evolve independently. A successful plain-text prompt
does not establish support for tool discovery, tool changes, thinking streams,
images, or a long conversation. The adapter and its fixture tests are the
compatibility boundary for thinking mode; direct mode bypasses it.

## Known incidents

| Symptom | Cause | Regression coverage |
| --- | --- | --- |
| Empty thinking answer | Thinking deltas emitted inside a text block | `ProtocolTests` stream and non-stream repair cases |
| Context-length 400 after screenshots | Output reserve and oversized base64 images consume the input window | Setup clamp and image-budget tests |
| Persistent 422 when tools appear mid-session | ModelScope rejects Anthropic `tool_addition` / `tool_removal` content blocks | `InlineToolTests`, including a notice after 699 messages, both Messages and token-count routes |

The inline-tool translation keeps notices in their original system-message
position and derives the current tool catalog from additions/removals. It does
not rewrite saved history. Missing definitions or unsupported inline references
produce a local 400 instead of silently dropping tool availability.

## Upgrade checks

1. Record the Claude Code version, Python version, model ID and repo commit.
2. Run `python3 -m unittest discover -s tests -v`. GitHub Actions runs these
   fixtures on pushes and pull requests; it also supports manual runs.
3. Run `claude-qwen doctor`, then optionally `claude-qwen doctor --live` for a
   small direct-mode provider check. The live option consumes provider quota.
4. Separately exercise thinking mode with a small prompt, then a harmless tool
   read and a tool-discovery/change turn. Verify the final response and tool
   arguments, not just MCP connection status. Check a resumed session too.
5. For a protocol failure, reduce it to a synthetic request and add a fixture
   before changing translation. Preserve notice text, tool schemas, call IDs,
   result content, and ordering. Do not fix errors by indiscriminately dropping
   unknown blocks or turning tool results into plain text.
6. Put the fix in this source repo, update every separately deployed adapter,
   and restart affected sessions. Keep a backup before replacing deployed files.

CI has no provider credentials and makes no live requests. Fixture runs cannot
detect a new upstream schema or a provider outage on their own; the live checks
above remain a separate step. No background monitor is installed by this repo.

## Safe issue reports

Include versions, adapter commit, HTTP status, validation `loc`, and a minimal
synthetic example of the offending block. Never publish keys, temporary local
tokens, full private transcripts, screenshots, or personal profile files.

The relevant Anthropic format is documented in
[mid-conversation system messages and tool changes](https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages).
That documentation describes Anthropic's API, not ModelScope feature support.
