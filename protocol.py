"""Normalize ModelScope's Anthropic content blocks without changing their contents."""
import copy
import json
import time
from collections import deque


class ProtocolError(Exception):
    pass


def sse_events(response, deadline, max_line=4 * 1024 * 1024, max_frame=8 * 1024 * 1024):
    """Parse SSE frames, including multiline data and comments, with bounded memory."""
    data, event_name, size = [], None, 0
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("ModelScope request exceeded its time limit")
        raw = response.readline(max_line + 1)
        if len(raw) > max_line:
            raise ProtocolError("ModelScope stream line exceeded its size limit")
        if not raw:
            if data:
                raise ProtocolError("ModelScope stream ended inside an SSE frame")
            return
        try:
            line = raw.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError:
            raise ProtocolError("ModelScope stream contained invalid UTF-8") from None
        size += len(raw)
        if size > max_frame:
            raise ProtocolError("ModelScope stream frame exceeded its size limit")
        if not line:
            if data:
                try:
                    value = json.loads("\n".join(data))
                except ValueError:
                    raise ProtocolError("ModelScope stream contained invalid JSON") from None
                if not isinstance(value, dict):
                    raise ProtocolError("ModelScope stream event was not an object")
                value.setdefault("type", event_name)
                yield value
            data, event_name, size = [], None, 0
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        elif line.startswith("event:"):
            event_name = line[6:].strip()


class StreamRepair:
    """Stream the first source block; queue later blocks to preserve parallel tools.

    One malformed source text block may become thinking + text output blocks.
    Tool fragments are never reopened, concatenated with another tool, or reordered
    within their source block. Signatures are preserved, never manufactured.
    """

    def __init__(self, max_pending=16 * 1024 * 1024):
        self.blocks, self.order = {}, deque()
        self.current, self.next_index = None, 0
        self.started, self.terminal = None, False
        self.pending_bytes, self.max_pending = 0, max_pending

    def _close(self):
        if self.current is not None:
            index = self.current[0]
            self.current = None
            return [{"type": "content_block_stop", "index": index}]
        return []

    def _open(self, source, kind, block):
        events = self._close()
        if kind == "tool_use" and block["tool_emitted"]:
            raise ProtocolError("ModelScope interrupted a tool's argument stream")
        if kind == block["meta"].get("type") and not block["meta_used"]:
            meta = copy.deepcopy(block["meta"])
            block["meta_used"] = True
        else:
            meta = {"type": kind}
        if kind == "text":
            meta.setdefault("text", "")
        elif kind == "thinking":
            meta.setdefault("thinking", "")
            meta.setdefault("signature", "")
        elif kind == "tool_use":
            if not meta.get("id") or not meta.get("name"):
                raise ProtocolError("ModelScope tool block lacked an id or name")
            block["tool_emitted"] = True
        self.current = (self.next_index, source, kind)
        events.append({"type": "content_block_start", "index": self.next_index, "content_block": meta})
        self.next_index += 1
        return events

    def _drain(self):
        events = []
        while self.order:
            source = self.order[0]
            block = self.blocks[source]
            meta = block["meta"]
            if not block["initialized"]:
                block["initialized"] = True
                if (meta.get("type") not in ("text", "thinking") or meta.get("text")
                        or meta.get("thinking") or meta.get("signature")):
                    events += self._open(source, meta.get("type"), block)
            while block["pending"]:
                delta, size = block["pending"].popleft()
                self.pending_bytes -= size
                kind = {"text_delta": "text", "thinking_delta": "thinking",
                        "signature_delta": "thinking", "input_json_delta": "tool_use"}.get(
                            delta.get("type"), meta.get("type"))
                if self.current is None or self.current[1:] != (source, kind):
                    events += self._open(source, kind, block)
                events.append({"type": "content_block_delta", "index": self.current[0], "delta": delta})
            if not block["stopped"]:
                break
            events += self._close()
            self.order.popleft()
            # Retain the index to reject duplicate starts, but discard all payloads.
            self.blocks[source] = None
        return events

    def feed(self, event):
        kind, source = event.get("type"), event.get("index")
        if not isinstance(kind, str) or not kind or len(kind) > 128 or "\n" in kind or "\r" in kind:
            raise ProtocolError("ModelScope sent an invalid event type")
        if self.terminal:
            if kind in ("message_stop", "ping"):
                return []
            raise ProtocolError("ModelScope sent data after the response ended")
        if kind == "message_start":
            if self.started is not None:
                if event == self.started:
                    return []
                raise ProtocolError("ModelScope sent conflicting message starts")
            self.started = copy.deepcopy(event)
            return [event]
        if kind == "error":
            self.terminal = True
            return [event]
        if kind == "ping":
            return [event]
        if self.started is None:
            raise ProtocolError("ModelScope stream lacked message_start")
        if kind == "content_block_start":
            if len(self.blocks) >= 4096:
                raise ProtocolError("ModelScope exceeded the content block limit")
            if not isinstance(source, int) or isinstance(source, bool) or source < 0 or source in self.blocks:
                raise ProtocolError("ModelScope sent an invalid content block index")
            meta = event.get("content_block")
            if not isinstance(meta, dict) or not isinstance(meta.get("type"), str):
                raise ProtocolError("ModelScope sent an invalid content block")
            self.blocks[source] = {"meta": meta, "pending": deque(), "initialized": False,
                                   "meta_used": False, "stopped": False, "tool_emitted": False}
            self.order.append(source)
            return self._drain()
        if kind in ("content_block_delta", "content_block_stop"):
            if not isinstance(source, int) or isinstance(source, bool):
                raise ProtocolError("ModelScope sent an invalid content block index")
            block = self.blocks.get(source)
            if block is None or block["stopped"]:
                raise ProtocolError("ModelScope referred to a missing or closed content block")
            if kind == "content_block_delta":
                delta = event.get("delta")
                if not isinstance(delta, dict) or not isinstance(delta.get("type"), str):
                    raise ProtocolError("ModelScope sent an invalid content delta")
                size = len(json.dumps(delta).encode())
                self.pending_bytes += size
                if self.pending_bytes > self.max_pending:
                    raise ProtocolError("ModelScope parallel content exceeded its buffer limit")
                block["pending"].append((delta, size))
            else:
                block["stopped"] = True
            return self._drain()
        if kind in ("message_delta", "message_stop"):
            if self.order:
                raise ProtocolError("ModelScope ended a message with unfinished content blocks")
            if kind == "message_stop":
                self.terminal = True
        # Preserve future event types rather than silently removing capabilities.
        return [event]

    def finish(self):
        if not self.terminal:
            raise ProtocolError("ModelScope stream ended before message_stop")


def normalize_message(message):
    """Fix trailing thinking within text/thinking runs, preserving tool boundaries."""
    if not isinstance(message, dict) or message.get("type") != "message" or not isinstance(message.get("content"), list):
        raise ProtocolError("ModelScope returned an invalid message")
    result, run = [], []

    def flush():
        result.extend(b for b in run if b.get("type") == "thinking")
        result.extend(b for b in run if b.get("type") != "thinking")
        run.clear()

    for block in message["content"]:
        if not isinstance(block, dict):
            raise ProtocolError("ModelScope returned an invalid content block")
        if block.get("type") in ("text", "thinking"):
            run.append(block)
        else:
            flush()
            result.append(block)
    flush()
    return {**message, "content": result}
