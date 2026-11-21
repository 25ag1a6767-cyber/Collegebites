"""
Peak-hour load test runner for CollegeBites API.
Usage: python tests/load_test.py --base-url http://127.0.0.1:8000 --concurrency 25 --requests 150
"""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx


def run_load_test(base_url: str, concurrency: int, total_requests: int) -> None:
    latencies: list[float] = []
    errors = 0

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        canteens = client.get("/api/v1/canteens").json()
        main_id = canteens[0]["id"]

        def hit_endpoint(idx: int) -> tuple[bool, float]:
            t0 = time.perf_counter()
            try:
                if idx % 3 == 0:
                    r = client.get("/api/v1/canteens")
                elif idx % 3 == 1:
                    r = client.get(f"/api/v1/menus/canteens/{main_id}/items")
                else:
                    r = client.get(f"/api/v1/pickup/board/{main_id}")
                return r.status_code == 200, (time.perf_counter() - t0) * 1000.0
            except Exception:
                return False, (time.perf_counter() - t0) * 1000.0

        t_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for ok, ms in pool.map(hit_endpoint, range(total_requests)):
                latencies.append(ms)
                if not ok:
                    errors += 1
        elapsed = time.perf_counter() - t_start

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else 0.0
    print(f"Total requests: {total_requests}, Concurrency: {concurrency}, Errors: {errors}")
    print(f"Throughput: {total_requests / elapsed:.1f} req/s, Mean: {statistics.mean(latencies):.1f} ms, P95: {p95:.1f} ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--requests", type=int, default=120)
    args = parser.parse_args()
    run_load_test(args.base_url, args.concurrency, args.requests)
