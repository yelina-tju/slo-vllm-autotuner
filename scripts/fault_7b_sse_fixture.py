"""Standalone CPU-only HTTP/SSE fault fixture, no upstream and no GPU.

Run --self-test to verify complete/truncated SSE and delayed first token.
Serve with --port 18081. Delay is supplied in X-Fault-Delay-Ms; truncation
via X-Fault-Truncate: 1. This is synthetic transport evidence, not inference.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from urllib.request import Request, urlopen


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        delay = float(self.headers.get('X-Fault-Delay-Ms', '0')) / 1000
        if not 0 <= delay <= 10:
            self.send_error(400, 'delay must be between 0 and 10000 ms')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.flush()
        deadline = time.monotonic() + delay
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(remaining)
        self.wfile.write(b'data: {"choices":[{"token_ids":[42],"text":"test"}]}\n\n')
        self.wfile.flush()
        if self.headers.get('X-Fault-Truncate') != '1':
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        self.close_connection = True


def self_test():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    rows = []
    try:
        for name, delay, truncate in [('healthy', 0, False), ('delayed', 100, False), ('truncated', 0, True)]:
            request = Request(f'http://127.0.0.1:{server.server_port}/v1/completions',
                data=b'{}', headers={'X-Fault-Delay-Ms': str(delay), 'X-Fault-Truncate': str(int(truncate))})
            started = time.monotonic()
            with urlopen(request, timeout=5) as response:
                first = response.read(1)
                first_s = time.monotonic() - started
                payload = first + response.read()
            assert b'token_ids' in payload
            assert (b'[DONE]' in payload) == (not truncate)
            if delay:
                assert first_s >= delay / 1000
            rows.append({'scenario': name, 'first_byte_s': first_s, 'has_done': b'[DONE]' in payload})
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    print(json.dumps({'status': 'passed', 'evidence': 'synthetic HTTP/SSE, CPU only', 'cases': rows}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--port', type=int, default=18081)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
