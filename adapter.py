#!/usr/bin/env python3
"""Per-session loopback adapter for claude-qwen --thinking. Python standard library only."""
import hmac
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from protocol import ProtocolError, StreamRepair, normalize_message, sse_events

UPSTREAM = "https://api-inference.modelscope.ai"
MAX_BODY = 64 * 1024 * 1024
# Base64 chars per image block. One full-resolution screenshot (~250 KB binary,
# ~340K base64 chars) costs well over 100K input tokens and can push a request
# past the gateway's input cap, which kills the session; a downscaled JPEG
# (~90 KB binary) passes. Oversized images become explicit placeholders.
MAX_IMAGE_CHARS = 120_000
SAFE_HEADERS = {"retry-after", "request-id", "x-request-id", "x-should-retry"}


@dataclass
class Config:
    upstream_key: str = field(repr=False)
    client_token: str = field(repr=False)
    upstream_url: str = UPSTREAM
    budget: int = 4096
    idle_timeout: float = 180
    total_timeout: float = 900
    client_timeout: float = 15
    max_body: int = MAX_BODY
    max_image_chars: int = MAX_IMAGE_CHARS
    max_connections: int = 16


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def limit_images(value, max_chars):
    """Replace oversized base64 image blocks with an explicit text placeholder.

    Walks the whole request payload; the standard library cannot re-encode
    images, so elision with instructions to downscale is the only safe bound.
    """
    if isinstance(value, dict):
        source = value.get("source")
        if (value.get("type") == "image" and isinstance(source, dict)
                and isinstance(source.get("data"), str) and len(source["data"]) > max_chars):
            return {"type": "text",
                    "text": ("[claude-qwen adapter: image elided, " + format(len(source["data"]), ",")
                             + " base64 chars exceeds the " + format(max_chars, ",")
                             + "-char per-image budget and would risk the gateway input limit."
                             " Downscale it first (macOS: sips -Z 1024 -s format jpeg in.png --out out.jpg),"
                             " then read the smaller file.]")}
        return {key: limit_images(item, max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [limit_images(item, max_chars) for item in value]
    return value


@contextmanager
def response_deadline(response, remaining):
    """Interrupt stalled or slowly dripping reads, including non-streaming JSON."""
    connection = socket.socket(fileno=os.dup(response.fileno()))
    lock, expired = threading.Lock(), threading.Event()
    active = True

    def abort():
        with lock:
            if active:
                expired.set()
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    timer = threading.Timer(max(0.001, remaining), abort)
    timer.daemon = True
    timer.start()
    try:
        try:
            yield expired
        except Exception:
            if expired.is_set():
                raise TimeoutError("ModelScope request exceeded its time limit") from None
            raise
        if expired.is_set():
            raise TimeoutError("ModelScope request exceeded its time limit")
    finally:
        with lock:
            active = False
            timer.cancel()
            connection.close()


class AdapterServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, config):
        self.config = config
        self.opener = urllib.request.build_opener(NoRedirect())
        self.slots = threading.BoundedSemaphore(config.max_connections)
        self.connections, self.lock = set(), threading.Lock()
        super().__init__(("127.0.0.1", 0), Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(timeout=0.25):
            try:
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\nRetry-After: 1\r\n\r\n')
            except OSError:
                pass
            self.shutdown_request(request)
            return
        with self.lock:
            self.connections.add(request)
        try:
            super().process_request(request, client_address)
        except BaseException:
            with self.lock:
                self.connections.discard(request)
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.lock:
                self.connections.discard(request)
            self.slots.release()

    def handle_error(self, *args):
        # Never print request bodies, credentials, or model content in server traces.
        pass

    def stop(self):
        self.shutdown()
        with self.lock:
            connections = list(self.connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ClaudeQwenAdapter/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.config.client_timeout)
        self.responded = False
        self.streaming = False

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.error(code, "invalid_request_error", "Unsupported or malformed local HTTP request")

    def redact(self, raw):
        for secret in (self.server.config.upstream_key, self.server.config.client_token):
            raw = raw.replace(secret.encode(), b"<redacted>")
        return raw

    def reply(self, status, body, content_type="application/json", headers=()):
        self.responded = True
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        for key, value in headers:
            if key.lower() in SAFE_HEADERS:
                self.send_header(key, self.redact(value.encode()).decode())
        self.end_headers()
        self.wfile.write(body)

    def error(self, status, kind, message):
        self.reply(status, encode({"type": "error", "error": {"type": kind, "message": message}}))

    def authorize(self):
        host = self.headers.get("Host", "")
        if host not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}") or self.headers.get("Origin"):
            self.error(403, "permission_error", "Only authenticated local CLI requests are accepted")
            return False
        authorization = self.headers.get("Authorization", "")
        supplied = authorization[7:] if authorization.startswith("Bearer ") else self.headers.get("x-api-key", "")
        if not hmac.compare_digest(supplied.encode(), self.server.config.client_token.encode()):
            self.error(401, "authentication_error", "Invalid local adapter credential")
            return False
        return True

    def route(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.fragment or len(self.path) > 4096:
            return None
        allowed = {"POST": {"/v1/messages", "/v1/messages/count_tokens"}, "GET": {"/v1/models"}}
        return parsed.path if parsed.path in allowed.get(self.command, set()) else None

    def handle_expect_100(self):
        self.error(417, "invalid_request_error", "Expect requests are not supported")
        return False

    def read_payload(self):
        config = self.server.config
        if self.headers.get("Transfer-Encoding") or not self.headers.get("Content-Length", "").isascii() or not self.headers.get("Content-Length", "").isdigit():
            raise ValueError("A Content-Length is required; chunked local requests are not supported")
        size = int(self.headers["Content-Length"])
        if size > config.max_body:
            raise OverflowError
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("Incomplete local request body")
        encoding = self.headers.get("Content-Encoding", "identity").lower()
        if encoding == "gzip":
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            raw = decoder.decompress(raw, config.max_body + 1)
            if len(raw) > config.max_body or decoder.unconsumed_tail:
                raise OverflowError
            if not decoder.eof or decoder.unused_data:
                raise ValueError("Invalid gzip request body")
        elif encoding != "identity":
            raise ValueError("Unsupported local request encoding")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Local request body must be valid JSON") from None
        if not isinstance(value, dict):
            raise ValueError("Local request body must be a JSON object")
        return value

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        try:
            self._handle_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except (TimeoutError, socket.timeout):
            if self.responded:
                if self.streaming:
                    self.stream_error("ModelScope connection timed out")
            else:
                self.error(504, "api_error", "ModelScope connection timed out")
        except (ProtocolError, ValueError, zlib.error) as error:
            if self.responded:
                if self.streaming:
                    self.stream_error(str(error) if isinstance(error, ProtocolError) else "Invalid ModelScope response")
            else:
                self.error(502, "api_error", "Invalid ModelScope response")
        except (OSError, urllib.error.URLError):
            if self.responded:
                if self.streaming:
                    self.stream_error("ModelScope connection failed")
            else:
                self.error(502, "api_error", "ModelScope connection failed")

    def _handle_request(self):
        if not self.authorize():
            return
        route = self.route()
        if route is None:
            return self.error(404, "not_found_error", "This adapter only supports Messages, token counting, and model discovery")
        config = self.server.config
        payload, wants_stream = None, False
        if self.command == "POST":
            try:
                payload = self.read_payload()
            except OverflowError:
                return self.error(413, "invalid_request_error", "Local request exceeded the 64 MiB body limit")
            except (ValueError, zlib.error) as error:
                return self.error(400, "invalid_request_error", str(error) if isinstance(error, ValueError) else "Invalid gzip request body")
            payload = limit_images(payload, config.max_image_chars)
            if route == "/v1/messages":
                maximum = payload.get("max_tokens")
                if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
                    return self.error(400, "invalid_request_error", "max_tokens must be a positive integer")
                if not isinstance(payload.get("stream", False), bool):
                    return self.error(400, "invalid_request_error", "stream must be a boolean")
                wants_stream = payload.get("stream", False)
                payload["thinking"] = {"type": "enabled", "budget_tokens": config.budget}
                payload["max_tokens"] = max(maximum, config.budget + 1024)
        headers = {"x-api-key": config.upstream_key, "Content-Type": "application/json",
                   "anthropic-version": self.headers.get("anthropic-version", "2023-06-01"),
                   "Accept-Encoding": "identity"}
        for key in ("anthropic-beta", "User-Agent"):
            if self.headers.get(key):
                headers[key] = self.headers[key]
        request = urllib.request.Request(config.upstream_url + self.path,
                                         data=encode(payload) if payload is not None else None,
                                         headers=headers, method=self.command)
        deadline = time.monotonic() + config.total_timeout
        try:
            upstream = self.server.opener.open(request, timeout=min(config.idle_timeout, config.total_timeout))
        except urllib.error.HTTPError as error:
            with error, response_deadline(error, deadline - time.monotonic()) as expired:
                if 300 <= error.code < 400:
                    return self.error(502, "api_error", "ModelScope redirect refused")
                raw = error.read(min(config.max_body, 1024 * 1024) + 1)
                if expired.is_set():
                    raise TimeoutError("ModelScope request exceeded its time limit")
                if len(raw) > min(config.max_body, 1024 * 1024):
                    return self.error(502, "api_error", "ModelScope error response exceeded its size limit")
                try:
                    detail = json.loads(self.redact(raw))
                    if not isinstance(detail, dict):
                        raise ValueError
                except ValueError:
                    detail = {"type": "error", "error": {"type": "api_error", "message": "ModelScope returned HTTP " + str(error.code)}}
                return self.reply(error.code, encode(detail), headers=error.headers.items())
        with upstream, response_deadline(upstream, deadline - time.monotonic()) as expired:
            content_type = upstream.headers.get_content_type()
            if wants_stream:
                if content_type != "text/event-stream":
                    return self.error(502, "api_error", "ModelScope did not return an event stream")
                self.responded, self.close_connection = True, True
                self.streaming = True
                self.connection.settimeout(config.idle_timeout)
                self.send_response(upstream.status)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                for key, value in upstream.headers.items():
                    if key.lower() in SAFE_HEADERS:
                        self.send_header(key, self.redact(value.encode()).decode())
                self.end_headers()
                repair = StreamRepair()
                for event in sse_events(upstream, deadline):
                    for fixed in repair.feed(event):
                        self.emit(fixed)
                repair.finish()
            else:
                raw = upstream.read(config.max_body + 1)
                if expired.is_set():
                    raise TimeoutError("ModelScope request exceeded its time limit")
                if len(raw) > config.max_body:
                    raise ProtocolError("ModelScope response exceeded its size limit")
                if content_type != "application/json":
                    raise ProtocolError("ModelScope did not return JSON")
                value = json.loads(raw)
                if route == "/v1/messages":
                    value = normalize_message(value)
                self.reply(upstream.status, self.redact(encode(value)), headers=upstream.headers.items())

    def emit(self, event):
        raw = self.redact(encode(event))
        self.wfile.write(b"event: " + str(event.get("type", "message")).encode() + b"\ndata: " + raw + b"\n\n")
        self.wfile.flush()

    def stream_error(self, message):
        try:
            self.emit({"type": "error", "error": {"type": "api_error", "message": message}})
        except OSError:
            pass


def thinking_profile(home):
    profile = home / ".claude-qwen-thinking"
    if not (profile / "settings.json").is_file():
        raise ValueError("Thinking profile is missing; restore ~/.claude-qwen-thinking/settings.json")
    return profile


def run_session(args, config, profile, claude):
    """Keep the CLI in the terminal's process group so its normal Ctrl-C works."""
    server = AdapterServer(config)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    child, stopping = None, threading.Event()
    old_handlers = {}

    def terminate(signum, frame):
        stopping.set()
        if child is not None and child.poll() is None:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                pass

    try:
        # Terminal SIGINT reaches both processes; let Claude handle interrupts.
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            old_handlers[sig] = signal.signal(sig, (lambda *_: None) if sig == signal.SIGINT else terminate)
        env = os.environ.copy()
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_CUSTOM_HEADERS"):
            env.pop(key, None)
        env.update({"CLAUDE_CONFIG_DIR": str(profile),
                    "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "ANTHROPIC_AUTH_TOKEN": config.client_token})
        child = subprocess.Popen([str(claude), *args], env=env)
        while True:
            try:
                code = child.wait(timeout=0.2)
                return code if code >= 0 else 128 - code
            except subprocess.TimeoutExpired:
                if stopping.is_set():
                    try:
                        code = child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        code = child.wait()
                    return code if code >= 0 else 128 - code
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        server.stop()
        thread.join(timeout=1)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def main(args):
    try:
        options = args[:args.index("--")] if "--" in args else args
        if any(option in ("--bg", "--background", "--cloud", "--desktop") or option.startswith(("--bg=", "--background=", "--cloud=", "--desktop=")) for option in options):
            raise ValueError("Thinking mode requires a foreground CLI session; background, cloud, and desktop modes cannot use its temporary adapter")
        try:
            budget = int(os.environ.get("CLAUDE_QWEN_THINKING_BUDGET", "4096"))
        except ValueError:
            raise ValueError("CLAUDE_QWEN_THINKING_BUDGET must be an integer") from None
        if not 1024 <= budget <= 15360:
            raise ValueError("CLAUDE_QWEN_THINKING_BUDGET must be between 1024 and 15360")
        key = os.environ.pop("ANTHROPIC_API_KEY", "").strip()
        if not key or any(char.isspace() for char in key):
            raise ValueError("Missing ModelScope key; launch with claude-qwen --thinking")
        home = Path.home()
        profile = thinking_profile(home)
        return run_session(args, Config(key, secrets.token_urlsafe(32), budget=budget),
                           profile, Path(os.environ["CLAUDE_QWEN_CLAUDE_BIN"]))
    except (ValueError, OSError) as error:
        # All ValueErrors originate in our own configuration validation.
        message = str(error) if isinstance(error, ValueError) else "Unable to start the local adapter or Claude Code"
        print("claude-qwen --thinking: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
