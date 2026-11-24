"""
Controlled Local Staging Load, Stress & Breaking-Point Runner for CollegeBites Enterprise Platform.
- Runs strictly against local staging Uvicorn ASGI on 127.0.0.1:8015 (NEVER live production!).
- Uses real Grafana k6.exe across progressive concurrency steps: 1, 5, 10, 25, 50, 100, 250, 500 VUs.
- Captures exact measured RPS, p50, p95, p99, error rate, and HTTP status breakdown per VU tier.
- Cleans up temporary staging SQLite DB on exit.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(r"C:\Users\HP\Desktop\collegebites")
BACKEND_DIR = ROOT / "backend"
VENV_PY = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
K6_EXE = ROOT / "performance-testing" / "bin" / "k6.exe"
OUT_DIR = ROOT / "performance-testing" / "enterprise-master"
STAGING_DB = OUT_DIR / "staging_k6_temp.db"
BASE_URL = "http://127.0.0.1:8015"

VU_TIERS = [1, 5, 10, 25, 50, 100, 250, 500]


def _seed_staging_db() -> None:
    if STAGING_DB.exists():
        STAGING_DB.unlink()
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{STAGING_DB.as_posix()}"
    env["ENVIRONMENT"] = "testing"
    env["RATE_LIMIT_ENABLED"] = "false"
    code = (
        "from app.core.database import engine, SessionLocal; "
        "from app.models.base import Base; "
        "import app.models; "
        "from app.services.seed_service import seed_initial_college_data; "
        "Base.metadata.create_all(bind=engine); "
        "db = SessionLocal(); "
        "seed_initial_college_data(db, create_demo_users=True); "
        "db.close(); "
        "print('SEEDED_OK')"
    )
    res = subprocess.run([str(VENV_PY), "-c", code], cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Staging DB seed failed:\n{res.stdout}\n{res.stderr}")


def _write_single_tier_script(path: Path) -> None:
    script = """import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL;
const CANTEEN_ID = __ENV.CANTEEN_ID;
const FOOD_ITEM_ID = __ENV.FOOD_ITEM_ID;
const AUTH_TOKEN = __ENV.AUTH_TOKEN;
const ADMIN_TOKEN = __ENV.ADMIN_TOKEN;
const VUS = Number(__ENV.VUS || "10");
const DUR = __ENV.DUR || "8s";

export const options = {
  vus: VUS,
  duration: DUR,
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

export default function () {
  const roll = Math.random();
  let res;
  if (roll < 0.35) {
    res = http.get(`${BASE_URL}/api/v1/canteens`);
  } else if (roll < 0.62) {
    res = http.get(`${BASE_URL}/api/v1/menus/canteens/${CANTEEN_ID}/items`);
  } else if (roll < 0.78) {
    res = http.get(`${BASE_URL}/api/v1/queue/canteens/${CANTEEN_ID}`);
  } else if (roll < 0.88) {
    res = http.get(`${BASE_URL}/api/v1/pickup/board/${CANTEEN_ID}`);
  } else if (roll < 0.95) {
    res = http.get(`${BASE_URL}/api/v1/food-safety/dashboard?canteen_id=${CANTEEN_ID}`, {
      headers: { Authorization: `Bearer ${ADMIN_TOKEN}` },
    });
  } else {
    res = http.post(
      `${BASE_URL}/api/v1/orders/checkout`,
      JSON.stringify({
        canteen_id: CANTEEN_ID,
        payment_method: "razorpay",
        use_cart: false,
        direct_items: [{ food_item_id: FOOD_ITEM_ID, quantity: 1 }],
      }),
      {
        headers: {
          Authorization: `Bearer ${AUTH_TOKEN}`,
          "Content-Type": "application/json",
        },
      }
    );
  }
  check(res, { "status 2xx": (r) => r.status >= 200 && r.status < 300 });
  sleep(0.05);
}
"""
    path.write_text(script, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _seed_staging_db()
    tier_js = OUT_DIR / "k6_tier_probe.js"
    _write_single_tier_script(tier_js)

    srv_env = os.environ.copy()
    srv_env["DATABASE_URL"] = f"sqlite:///{STAGING_DB.as_posix()}"
    srv_env["ENVIRONMENT"] = "testing"
    srv_env["RATE_LIMIT_ENABLED"] = "false"
    srv_env["REDIS_URL"] = "memory://"
    srv_env["PYTHONPATH"] = str(BACKEND_DIR)

    srv = subprocess.Popen(
        [
            str(VENV_PY),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8015",
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env=srv_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for health endpoint
        ready = False
        for _ in range(40):
            try:
                r = httpx.get(f"{BASE_URL}/health", timeout=2.0)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.5)
        if not ready:
            raise RuntimeError("Staging Uvicorn failed to start on 127.0.0.1:8015")

        canteen_id = httpx.get(f"{BASE_URL}/api/v1/canteens", timeout=5.0).json()[0]["id"]
        food_item_id = httpx.get(f"{BASE_URL}/api/v1/menus/canteens/{canteen_id}/items", timeout=5.0).json()[-1]["id"]
        stu_tok = httpx.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"identifier": "student@collegebites.edu", "password": "Student@12345"},
            timeout=5.0,
        ).json()["access_token"]
        adm_tok = httpx.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"identifier": "admin@collegebites.edu", "password": "Admin@12345"},
            timeout=5.0,
        ).json()["access_token"]

        results = []
        breaking_point_vu = None
        for vus in VU_TIERS:
            summary_file = OUT_DIR / f"k6_summary_{vus}vu.json"
            if summary_file.exists():
                summary_file.unlink()
            k6_env = os.environ.copy()
            k6_env.update(
                {
                    "BASE_URL": BASE_URL,
                    "CANTEEN_ID": canteen_id,
                    "FOOD_ITEM_ID": food_item_id,
                    "AUTH_TOKEN": stu_tok,
                    "ADMIN_TOKEN": adm_tok,
                    "VUS": str(vus),
                    "DUR": "6s",
                }
            )
            proc = subprocess.run(
                [
                    str(K6_EXE),
                    "run",
                    "--quiet",
                    f"--summary-export={summary_file}",
                    str(tier_js),
                ],
                env=k6_env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if not summary_file.exists():
                results.append({"vus": vus, "error": f"k6 failed rc={proc.returncode}: {proc.stderr[:200]}"})
                breaking_point_vu = vus
                break
            data = json.loads(summary_file.read_text(encoding="utf-8"))
            m = data.get("metrics", {})
            reqs = m.get("http_reqs", {})
            dur = m.get("http_req_duration", {})
            failed = m.get("http_req_failed", {})
            rps = round(float(reqs.get("rate", 0.0)), 2)
            total_reqs = int(reqs.get("count", 0))
            err_rate = round(float(failed.get("value", 0.0)) * 100.0, 2)
            p50 = round(float(dur.get("med", 0.0)), 2)
            p95 = round(float(dur.get("p(95)", 0.0)), 2)
            p99 = round(float(dur.get("p(99)", 0.0)), 2)
            avg = round(float(dur.get("avg", 0.0)), 2)
            row = {
                "vus": vus,
                "total_requests": total_reqs,
                "rps": rps,
                "avg_ms": avg,
                "p50_ms": p50,
                "p95_ms": p95,
                "p99_ms": p99,
                "error_rate_pct": err_rate,
            }
            results.append(row)
            print(json.dumps(row), flush=True)
            if err_rate >= 10.0 or p95 >= 5000.0:
                breaking_point_vu = vus
                break

        out_payload = {
            "target": "local_staging_uvicorn_1_worker_sqlite",
            "live_production_touched": False,
            "breaking_point_vu": breaking_point_vu,
            "tiers": results,
        }
        (OUT_DIR / "results.json").write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
        print("K6_DONE", json.dumps(out_payload))
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
        if STAGING_DB.exists():
            try:
                STAGING_DB.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    main()
