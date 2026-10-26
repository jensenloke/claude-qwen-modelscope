"""Disposable fixtures only; this suite never contacts ModelScope or loads a real key."""
import contextlib
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adapter import AdapterServer, Config, encode
from protocol import ProtocolError, StreamRepair, normalize_message, sse_events


def event(kind, **data):
    return {"type": kind, **data}


def start(index, kind="text", **data):
    return event("content_block_start", index=index, content_block={"type": kind, **data})


def delta(index, kind, **data):
    return event("content_block_delta", index=index, delta={"type": kind, **data})


MESSAGE_START = event("message_start", message={"id": "msg_test", "type": "message", "role": "assistant",
                                               "model": "test", "content": [], "usage": {"input_tokens": 1, "output_tokens": 0}})
END = [event("message_delta", delta={"stop_reason": "end_turn"}, usage={"output_tokens": 3}), event("message_stop")]
BROKEN = [MESSAGE_START, start(0, text=""), delta(0, "thinking_delta", thinking="private fixture reasoning"),
          delta(0, "text_delta", text="OK"), event("content_block_stop", index=0), *END]


def repair(events):
    normalizer, result = StreamRepair(), []
    for value in events:
        result.extend(normalizer.feed(value))
    normalizer.finish()
    return result


def assembled(events):
    blocks, active = {}, set()
    for value in events:
        kind, index = value.get("type"), value.get("index")
        if kind == "content_block_start":
            assert not active, "Output blocks must be serialized"
            assert index not in blocks
            blocks[index] = dict(value["content_block"])
            active.add(index)
        elif kind == "content_block_delta":
            assert index in active
            change = value["delta"]
            expected = {"text_delta": "text", "thinking_delta": "thinking", "signature_delta": "thinking",
                        "input_json_delta": "tool_use"}.get(change["type"])
            if expected:
                assert blocks[index]["type"] == expected
            for key in ("text", "thinking", "signature", "partial_json"):
                if key in change:
                    blocks[index][key] = blocks[index].get(key, "") + change[key]
        elif kind == "content_block_stop":
            assert index in active
            active.remove(index)
    assert not active
    return list(blocks.values())


class ProtocolTests(unittest.TestCase):
    def test_mislabeled_thinking_and_text(self):
        blocks = assembled(repair(BROKEN))
        self.assertEqual([b["type"] for b in blocks], ["thinking", "text"])
        self.assertEqual(blocks[0]["thinking"], "private fixture reasoning")
        self.assertEqual(blocks[0]["signature"], "")
        self.assertEqual(blocks[1]["text"], "OK")

    def test_valid_stream_signatures_and_unknown_events_survive(self):
        values = [MESSAGE_START, start(0, "thinking", thinking="", signature=""),
                  delta(0, "thinking_delta", thinking="fixture"), delta(0, "signature_delta", signature="opaque-provider-signature"),
                  event("content_block_stop", index=0), start(1, text=""), delta(1, "text_delta", text="OK"),
                  event("content_block_stop", index=1), event("future_notice", data={"opaque": True}), *END]
        self.assertEqual(repair(values), values)

    def test_parallel_tools_keep_ids_and_exact_fragment_order(self):
        values = [MESSAGE_START, start(0, "tool_use", id="tool_a", name="Read", input={}),
                  start(1, "tool_use", id="tool_b", name="Read", input={}),
                  delta(0, "input_json_delta", partial_json='{"file_path":"a'),
                  delta(1, "input_json_delta", partial_json='{"file_path":"b'),
                  delta(0, "input_json_delta", partial_json='.txt"}'), event("content_block_stop", index=0),
                  delta(1, "input_json_delta", partial_json='.txt"}'), event("content_block_stop", index=1), *END]
        blocks = assembled(repair(values))
        self.assertEqual([b["id"] for b in blocks], ["tool_a", "tool_b"])
        self.assertEqual([json.loads(b["partial_json"]) for b in blocks],
                         [{"file_path": "a.txt"}, {"file_path": "b.txt"}])

    def test_duplicate_message_start_and_empty_text_are_removed(self):
        values = [MESSAGE_START, MESSAGE_START, start(0, text=""), event("content_block_stop", index=0),
                  start(1, text=""), delta(1, "text_delta", text="OK"), event("content_block_stop", index=1), *END]
        result = repair(values)
        self.assertEqual(sum(e["type"] == "message_start" for e in result), 1)
        self.assertEqual(assembled(result), [{"type": "text", "text": "OK"}])

    def test_missing_stops_and_invalid_indices_fail(self):
        for values in [BROKEN[:-1], BROKEN[:3] + END,
                       [MESSAGE_START, delta({}, "text_delta", text="bad")],
                       [MESSAGE_START, start(0, text=""), start(0, text="")]]:
            with self.subTest(values=values), self.assertRaises(ProtocolError):
                repair(values)

    def test_parallel_buffer_is_bounded(self):
        normalizer = StreamRepair(max_pending=80)
        for value in [MESSAGE_START, start(0, text=""), start(1, text="")]:
            normalizer.feed(value)
        with self.assertRaises(ProtocolError):
            normalizer.feed(delta(1, "text_delta", text="x" * 100))

    def test_sse_multiline_comments_and_truncation(self):
        data = b': heartbeat\r\nevent: ping\r\ndata: {"type":\r\ndata: "ping"}\r\n\r\n'
        self.assertEqual(list(sse_events(io.BytesIO(data), time.monotonic() + 1)), [{"type": "ping"}])
        for raw in [b'data: {"type":"ping"}\n', b'data: bad\n\n', b'data: \xff\n\n']:
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):
                list(sse_events(io.BytesIO(raw), time.monotonic() + 1))
        with self.assertRaises(ProtocolError):
            list(sse_events(io.BytesIO(b"x" * 30), time.monotonic() + 1, max_line=20))
        with self.assertRaises(TimeoutError):
            list(sse_events(io.BytesIO(data), time.monotonic() - 1))

    def test_nonstream_thinking_reorder_preserves_tool_boundaries(self):
        tool = {"type": "tool_use", "id": "t", "name": "Read", "input": {"file_path": "x"}}
        message = {"type": "message", "content": [{"type": "text", "text": "prelude"},
                   {"type": "thinking", "thinking": "first", "signature": "s1"}, tool,
                   {"type": "text", "text": "answer"}, {"type": "thinking", "thinking": "second", "signature": "s2"}]}
        result = normalize_message(message)
        self.assertEqual([b["type"] for b in result["content"]], ["thinking", "text", "tool_use", "thinking", "text"])
        self.assertIs(result["content"][2], tool)


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.do_POST()

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.requests.append((self.path, dict(self.headers), json.loads(raw) if raw else None))
        mode = self.server.mode
        if mode == "timeout":
            time.sleep(0.2)
        status = 429 if mode in ("rate_limit", "error_drip") else 302 if mode == "redirect" else 200
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream" if mode in ("stream", "truncated", "stream_error") else "application/json")
        if mode == "rate_limit":
            self.send_header("Retry-After", "3")
        if mode == "redirect":
            self.send_header("Location", "http://untrusted.invalid/steal")
        self.end_headers()
        if mode in ("json_drip", "error_drip"):
            try:
                for _ in range(50):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.01)
            except OSError:
                pass
            return
        if mode in ("stream", "truncated", "stream_error"):
            values = BROKEN if mode == "stream" else BROKEN[:-1] if mode == "truncated" else [MESSAGE_START, event("error", error={"type": "overloaded_error", "message": "upstream-secret local-token"})]
            body = b"".join(b"event: " + e["type"].encode() + b"\ndata: " + encode(e) + b"\n\n" for e in values)
        elif mode == "rate_limit":
            body = encode({"type": "error", "error": {"type": "rate_limit_error", "message": "upstream-secret local-token"}})
        elif self.path.startswith("/v1/models"):
            body = encode({"data": [{"id": "test"}]})
        elif self.path.startswith("/v1/messages/count_tokens"):
            body = encode({"input_tokens": 10})
        else:
            body = encode({"type": "message", "content": [{"type": "text", "text": "OK"}, {"type": "thinking", "thinking": "fixture", "signature": "opaque"}]})
        try:
            self.wfile.write(body)
        except OSError:
            pass


@contextlib.contextmanager
def servers(mode="stream", **overrides):
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    fixture.daemon_threads, fixture.mode, fixture.requests = True, mode, []
    config = Config("upstream-secret", "local-token", upstream_url=f"http://127.0.0.1:{fixture.server_port}", **overrides)
    adapter = AdapterServer(config)
    threads = [threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True) for s in (fixture, adapter)]
    for thread in threads:
        thread.start()
    try:
        yield adapter, fixture
    finally:
        adapter.stop()
        fixture.shutdown()
        fixture.server_close()
        for thread in threads:
            thread.join(timeout=1)


def request(adapter, payload=None, route="/v1/messages", headers=None, raw=None, method=None):
    base_headers = {"Authorization": "Bearer local-token", "Content-Type": "application/json"}
    base_headers.update(headers or {})
    if payload is None:
        payload = {"model": "test", "max_tokens": 8192, "stream": True, "messages": []}
    data = raw if raw is not None else encode(payload)
    req = urllib.request.Request(f"http://127.0.0.1:{adapter.server_port}" + route,
                                 data=None if method == "GET" else data, headers=base_headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=2)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, dict(response.headers), response.read()


class HTTPTests(unittest.TestCase):
    def test_live_http_repair_and_fixed_upstream_auth(self):
        with servers() as (adapter, fixture):
            status, _, raw = request(adapter)
            self.assertEqual(status, 200)
            events = list(sse_events(io.BytesIO(raw), time.monotonic() + 1))
            self.assertEqual([b["type"] for b in assembled(events)], ["thinking", "text"])
            path, headers, payload = fixture.requests[0]
            lowered = {key.lower(): value for key, value in headers.items()}
            self.assertEqual(lowered.get("x-api-key"), "upstream-secret")
            self.assertNotIn("authorization", lowered)
            self.assertEqual(payload["thinking"], {"type": "enabled", "budget_tokens": 4096})

    def test_auth_origin_host_and_unknown_routes_do_not_reach_upstream(self):
        with servers() as (adapter, fixture):
            for headers, route, status in [({"Authorization": "Bearer wrong"}, "/v1/messages", 401),
                                            ({"Origin": "https://example.com"}, "/v1/messages", 403),
                                            ({"Host": "example.com"}, "/v1/messages", 403),
                                            ({}, "/v1/not-an-api", 404)]:
                self.assertEqual(request(adapter, headers=headers, route=route)[0], status)
            self.assertEqual(fixture.requests, [])

    def test_gzip_and_request_limits(self):
        with servers("json", max_body=1024) as (adapter, fixture):
            self.assertEqual(request(adapter, raw=gzip.compress(encode({"model": "test", "max_tokens": 30})),
                                     headers={"Content-Encoding": "gzip"})[0], 200)
            self.assertEqual(fixture.requests[0][2]["max_tokens"], 5120)
            self.assertEqual(request(adapter, raw=gzip.compress(b"x" * 2048), headers={"Content-Encoding": "gzip"})[0], 413)
            self.assertEqual(request(adapter, raw=b"x" * 1025)[0], 413)
            self.assertEqual(request(adapter, raw=b"not-json")[0], 400)
            self.assertEqual(request(adapter, payload={"max_tokens": True})[0], 400)

    def test_upstream_errors_keep_status_retry_and_redact_credentials(self):
        with servers("rate_limit") as (adapter, _):
            status, headers, raw = request(adapter)
            self.assertEqual(status, 429)
            self.assertEqual(headers.get("Retry-After"), "3")
            self.assertNotIn(b"upstream-secret", raw)
            self.assertNotIn(b"local-token", raw)
            self.assertEqual(json.loads(raw)["error"]["type"], "rate_limit_error")

    def test_failed_upstream_request_does_not_poison_next_request(self):
        with servers("rate_limit") as (adapter, fixture):
            self.assertEqual(request(adapter)[0], 429)
            fixture.mode = "stream"
            self.assertEqual(request(adapter)[0], 200)

    def test_redirects_are_refused(self):
        with servers("redirect") as (adapter, fixture):
            self.assertEqual(request(adapter)[0], 502)
            self.assertEqual(len(fixture.requests), 1)

    def test_timeouts_and_wrong_content_type(self):
        with servers("timeout", idle_timeout=0.05) as (adapter, _):
            self.assertEqual(request(adapter)[0], 504)
        with servers("json") as (adapter, _):
            self.assertEqual(request(adapter)[0], 502)

    def test_absolute_deadline_interrupts_dripping_json(self):
        for mode in ("json_drip", "error_drip"):
            with self.subTest(mode=mode), servers(mode, idle_timeout=1, total_timeout=0.05) as (adapter, _):
                began = time.monotonic()
                self.assertEqual(request(adapter, payload={"model": "test", "max_tokens": 8192})[0], 504)
                self.assertLess(time.monotonic() - began, 0.4)

    def test_connection_limit_and_recovery(self):
        with servers(max_connections=1) as (adapter, fixture):
            idle = socket.create_connection(("127.0.0.1", adapter.server_port), timeout=1)
            try:
                deadline = time.monotonic() + 1
                while not adapter.connections and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertEqual(request(adapter)[0], 503)
                self.assertEqual(fixture.requests, [])
            finally:
                idle.close()
            deadline = time.monotonic() + 1
            while adapter.connections and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(request(adapter)[0], 200)

    def test_truncation_emits_error_without_faking_success(self):
        with servers("truncated") as (adapter, _):
            status, _, raw = request(adapter)
            values = list(sse_events(io.BytesIO(raw), time.monotonic() + 1))
            self.assertEqual(status, 200)
            self.assertEqual(values[-1]["type"], "error")
            self.assertNotIn("message_stop", [e["type"] for e in values])

    def test_provider_stream_errors_are_preserved_and_redacted(self):
        with servers("stream_error") as (adapter, _):
            _, _, raw = request(adapter)
            values = list(sse_events(io.BytesIO(raw), time.monotonic() + 1))
            self.assertEqual(values[-1]["error"]["type"], "overloaded_error")
            self.assertNotIn(b"upstream-secret", raw)

    def test_nonstream_and_metadata_routes(self):
        with servers("json") as (adapter, fixture):
            _, _, raw = request(adapter, payload={"model": "test", "max_tokens": 8192})
            self.assertEqual([b["type"] for b in json.loads(raw)["content"]], ["thinking", "text"])
            self.assertEqual(json.loads(request(adapter, route="/v1/models", method="GET")[2])["data"][0]["id"], "test")
            self.assertEqual(json.loads(request(adapter, route="/v1/messages/count_tokens", payload={"model": "test"})[2]), {"input_tokens": 10})
            self.assertNotIn("thinking", fixture.requests[-1][2])


class LifecycleTests(unittest.TestCase):
    def launch(self, directory, wait):
        root = Path(directory)
        child = root / "child.py"
        record = root / "record.json"
        child.write_text('''import hashlib,json,os,socket,time
from pathlib import Path
from urllib.parse import urlsplit
url=urlsplit(os.environ['ANTHROPIC_BASE_URL'])
with socket.create_connection((url.hostname,url.port),timeout=1): pass
Path(os.environ['PROBE_RECORD']).write_text(json.dumps({'port':url.port,'pid':os.getpid(),'upstream_key_present':'ANTHROPIC_API_KEY' in os.environ,'token_hash':hashlib.sha256(os.environ['ANTHROPIC_AUTH_TOKEN'].encode()).hexdigest()}))
if os.environ['PROBE_WAIT']=='1':
 while True: time.sleep(.1)
''')
        code = "from adapter import Config,run_session;from pathlib import Path;import sys;raise SystemExit(run_session(sys.argv[1:],Config('upstream-secret','local-token-'+str(__import__('os').getpid())),Path('.'),Path(sys.executable)))"
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(ROOT), "PROBE_RECORD": str(record), "PROBE_WAIT": "1" if wait else "0",
                    "ANTHROPIC_API_KEY": "upstream-secret"})
        process = subprocess.Popen([sys.executable, "-c", code, str(child)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        deadline = time.monotonic() + 4
        while not record.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not record.exists():
            process.kill()
            stdout, stderr = process.communicate()
            self.fail("Child failed to start: " + stderr.decode())
        return process, json.loads(record.read_text())

    def assert_closed(self, port):
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.2)

    def test_exit_cleanup_and_upstream_secret_not_in_cli_environment(self):
        with tempfile.TemporaryDirectory() as root:
            process, record = self.launch(root, False)
            process.communicate(timeout=4)
            self.assertEqual(process.returncode, 0)
            self.assertFalse(record["upstream_key_present"])
            self.assert_closed(record["port"])

    def test_concurrent_sessions_and_signal_cleanup(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            processes = []
            try:
                for root in (first, second):
                    processes.append(self.launch(root, True))
                self.assertNotEqual(processes[0][1]["port"], processes[1][1]["port"])
                self.assertNotEqual(processes[0][1]["token_hash"], processes[1][1]["token_hash"])
            finally:
                for process, record in processes:
                    process.terminate()
                    process.communicate(timeout=12)
                    self.assertEqual(process.returncode, 143)
                    self.assert_closed(record["port"])
                    with self.assertRaises(ProcessLookupError):
                        os.kill(record["pid"], 0)


class WrapperRegressionTests(unittest.TestCase):
    def test_invalid_budgets_and_detached_modes_fail_before_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = [(["--bg"], "4096", "foreground"), ([], "not-an-integer", "integer"),
                     ([], "0", "between 1024"), ([], "20000", "between 1024")]
            for args, budget, message in cases:
                with self.subTest(args=args, budget=budget):
                    env = {"PATH": os.environ.get("PATH", ""), "HOME": directory,
                           "CLAUDE_QWEN_THINKING_BUDGET": budget, "ANTHROPIC_API_KEY": "fixture-key"}
                    result = subprocess.run([sys.executable, str(ROOT / "adapter.py"), *args],
                                            env=env, capture_output=True, text=True, timeout=3)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(message, result.stderr)



if __name__ == "__main__":
    unittest.main(verbosity=2)
