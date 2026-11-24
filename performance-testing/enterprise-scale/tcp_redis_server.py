"""Lightweight local TCP Redis server backed by fakeredis.TcpFakeServer.

Used by the isolated multi-worker staging load-test harness so that all Uvicorn
workers share a genuine TCP Redis (`redis://127.0.0.1:6379/0`) instance for
L2 response caching, namespace invalidation counters, and SlowAPI distributed
rate limiting — without requiring Docker or a system Redis service.
"""

import argparse
import signal
import sys
import threading

from fakeredis import TcpFakeServer


def main() -> None:
    parser = argparse.ArgumentParser(description="Start local TCP Redis server for staging benchmarks")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    args = parser.parse_args()

    server = TcpFakeServer((args.host, args.port), server_type="redis")
    server.daemon_threads = True
    server.allow_reuse_address = True
    stop_event = threading.Event()

    def _handle_stop(_signum, _frame):
        stop_event.set()
        try:
            server.shutdown()
        except Exception:
            pass

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"TCP_REDIS_READY {args.host}:{args.port}", flush=True)

    try:
        while not stop_event.is_set() and thread.is_alive():
            stop_event.wait(timeout=0.5)
    finally:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
