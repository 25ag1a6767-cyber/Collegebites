"""
CollegeBites Secure Local Kitchen Print Agent
---------------------------------------------
Runs on the physical kitchen computer connected to a USB, Serial, OS-spooler,
or LAN TCP/9100 ESC/POS thermal printer. Authenticates to the CollegeBites cloud
backend using X-Print-Agent-Id + X-Print-Agent-Token, polls/heartbeats printer &
paper-roll status, streams the exact canonical customer receipt segment-by-segment,
pauses safely on out-of-paper without losing progress, and automatically resumes
from the exact segment/byte checkpoint as soon as a new paper roll is loaded.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("collegebites.print_agent")

DLE_EOT_PRINTER = b"\x10\x04\x01"
DLE_EOT_OFFLINE = b"\x10\x04\x02"
DLE_EOT_PAPER = b"\x10\x04\x04"


def decode_escpos_status(status_byte: Optional[int], offline_byte: Optional[int], paper_byte: Optional[int]) -> dict[str, Any]:
    online = True if status_byte is None else not bool(status_byte & 0x08)
    cover_err = False if offline_byte is None else bool(offline_byte & 0x64)
    paper_out = False if paper_byte is None else bool(paper_byte & 0x60)
    paper_low = False if paper_byte is None else bool(paper_byte & 0x0C)

    if paper_out:
        paper_status = "out_of_paper"
        online = False
    elif paper_low:
        paper_status = "low"
    elif paper_byte is not None:
        paper_status = "available"
    else:
        paper_status = "available"

    return {
        "is_connected": True,
        "is_online": bool(online and not cover_err and not paper_out),
        "paper_status": paper_status,
        "supports_realtime_status": paper_byte is not None,
    }


@dataclass
class PrinterProbeResult:
    is_connected: bool
    is_online: bool
    paper_status: str
    supports_realtime_status: bool
    supports_resume_offset: bool
    last_error: Optional[str] = None


class BaseTransport:
    supports_resume_offset: bool = True

    def probe(self) -> PrinterProbeResult:
        raise NotImplementedError

    def send_segments(
        self,
        segments: list[dict[str, Any]],
        start_index: int,
        on_progress: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError


class NetworkEscPosTransport(BaseTransport):
    supports_resume_offset = True

    def __init__(self, host: str, port: int = 9100, timeout: float = 3.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _query_byte(self, sock: socket.socket, cmd: bytes) -> Optional[int]:
        sock.sendall(cmd)
        try:
            data = sock.recv(1)
            return data[0] if data else None
        except socket.timeout:
            return None

    def probe(self) -> PrinterProbeResult:
        try:
            with socket.create_connection((self.host, self.port), timeout=1.8) as sock:
                sock.settimeout(1.0)
                b1 = self._query_byte(sock, DLE_EOT_PRINTER)
                b2 = self._query_byte(sock, DLE_EOT_OFFLINE)
                b4 = self._query_byte(sock, DLE_EOT_PAPER)
                st = decode_escpos_status(b1, b2, b4)
                return PrinterProbeResult(
                    is_connected=st["is_connected"],
                    is_online=st["is_online"],
                    paper_status=st["paper_status"],
                    supports_realtime_status=st["supports_realtime_status"],
                    supports_resume_offset=True,
                )
        except Exception as exc:
            return PrinterProbeResult(
                is_connected=False,
                is_online=False,
                paper_status="unknown",
                supports_realtime_status=True,
                supports_resume_offset=True,
                last_error=f"TCP printer unreachable at {self.host}:{self.port} ({exc})",
            )

    def send_segments(self, segments: list[dict[str, Any]], start_index: int, on_progress: Any) -> dict[str, Any]:
        printed_idx = start_index
        printed_bytes = segments[start_index - 1]["byte_end"] if start_index > 0 else 0
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                for seg in segments[start_index:]:
                    b4 = self._query_byte(sock, DLE_EOT_PAPER)
                    if b4 is not None and (b4 & 0x60):
                        return {
                            "status": "paused",
                            "reason": "out_of_paper",
                            "paper_status": "out_of_paper",
                            "printed_segment_index": printed_idx,
                            "printed_byte_offset": printed_bytes,
                        }
                    raw = base64.b64decode(seg["base64_bytes"])
                    sock.sendall(raw)
                    printed_idx = int(seg["index"]) + 1
                    printed_bytes = int(seg["byte_end"])
                    on_progress(printed_idx, printed_bytes)
            return {
                "status": "completed",
                "printed_segment_index": printed_idx,
                "printed_byte_offset": printed_bytes,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error_message": f"TCP send interrupted at byte {printed_bytes}: {exc}",
                "printer_offline": True,
                "printed_segment_index": printed_idx,
                "printed_byte_offset": printed_bytes,
            }


class SerialEscPosTransport(BaseTransport):
    supports_resume_offset = True

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

    def _open_serial(self):
        import serial  # type: ignore

        return serial.Serial(self.port, baudrate=self.baudrate, timeout=0.8, write_timeout=self.timeout)

    def probe(self) -> PrinterProbeResult:
        try:
            with self._open_serial() as ser:
                ser.write(DLE_EOT_PAPER)
                resp = ser.read(1)
                b4 = resp[0] if resp else None
                st = decode_escpos_status(None, None, b4)
                return PrinterProbeResult(
                    is_connected=True,
                    is_online=st["is_online"],
                    paper_status=st["paper_status"],
                    supports_realtime_status=b4 is not None,
                    supports_resume_offset=True,
                )
        except Exception as exc:
            return PrinterProbeResult(
                is_connected=False,
                is_online=False,
                paper_status="unknown",
                supports_realtime_status=True,
                supports_resume_offset=True,
                last_error=f"Serial printer error on {self.port}: {exc}",
            )

    def send_segments(self, segments: list[dict[str, Any]], start_index: int, on_progress: Any) -> dict[str, Any]:
        printed_idx = start_index
        printed_bytes = segments[start_index - 1]["byte_end"] if start_index > 0 else 0
        try:
            with self._open_serial() as ser:
                for seg in segments[start_index:]:
                    ser.write(DLE_EOT_PAPER)
                    resp = ser.read(1)
                    if resp and (resp[0] & 0x60):
                        return {
                            "status": "paused",
                            "reason": "out_of_paper",
                            "paper_status": "out_of_paper",
                            "printed_segment_index": printed_idx,
                            "printed_byte_offset": printed_bytes,
                        }
                    raw = base64.b64decode(seg["base64_bytes"])
                    ser.write(raw)
                    ser.flush()
                    printed_idx = int(seg["index"]) + 1
                    printed_bytes = int(seg["byte_end"])
                    on_progress(printed_idx, printed_bytes)
            return {
                "status": "completed",
                "printed_segment_index": printed_idx,
                "printed_byte_offset": printed_bytes,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error_message": f"Serial write interrupted at byte {printed_bytes}: {exc}",
                "printer_offline": True,
                "printed_segment_index": printed_idx,
                "printed_byte_offset": printed_bytes,
            }


class OsSpoolerTransport(BaseTransport):
    """OS print spooler fallback (Windows win32print or CUPS lp -o raw). Safe controlled-reprint recovery."""

    supports_resume_offset = False

    def __init__(self, printer_name: str):
        self.printer_name = printer_name

    def probe(self) -> PrinterProbeResult:
        if platform.system().lower() == "windows":
            try:
                import win32print  # type: ignore

                h = win32print.OpenPrinter(self.printer_name)
                try:
                    info = win32print.GetPrinter(h, 2)
                finally:
                    win32print.ClosePrinter(h)
                status = int(info.get("Status", 0))
                paper_out = bool(status & 0x00000010)
                offline = bool(status & 0x00000080)
                return PrinterProbeResult(
                    is_connected=True,
                    is_online=not (offline or paper_out),
                    paper_status="out_of_paper" if paper_out else "available",
                    supports_realtime_status=True,
                    supports_resume_offset=False,
                )
            except Exception as exc:
                return PrinterProbeResult(
                    is_connected=False,
                    is_online=False,
                    paper_status="unknown",
                    supports_realtime_status=False,
                    supports_resume_offset=False,
                    last_error=f"Windows spooler unavailable for '{self.printer_name}': {exc}",
                )
        if shutil.which("lpstat"):
            res = subprocess.run(["lpstat", "-p", self.printer_name], capture_output=True, text=True)
            ok = res.returncode == 0
            return PrinterProbeResult(
                is_connected=ok,
                is_online=ok and "disabled" not in res.stdout.lower(),
                paper_status="unknown" if not ok else "available",
                supports_realtime_status=False,
                supports_resume_offset=False,
                last_error=None if ok else res.stderr.strip(),
            )
        return PrinterProbeResult(False, False, "unknown", False, False, "No OS print spooler tool found")

    def send_segments(self, segments: list[dict[str, Any]], start_index: int, on_progress: Any) -> dict[str, Any]:
        # OS spooler accepts a full raw ESC/POS document atomically; uses controlled continuation on recovery.
        full_bytes = b"".join(base64.b64decode(seg["base64_bytes"]) for seg in segments)
        total_segs = len(segments)
        total_bytes = segments[-1]["byte_end"] if segments else 0
        try:
            if platform.system().lower() == "windows":
                import win32print  # type: ignore

                h = win32print.OpenPrinter(self.printer_name)
                try:
                    win32print.StartDocPrinter(h, 1, ("CollegeBites Kitchen Receipt", None, "RAW"))
                    try:
                        win32print.StartPagePrinter(h)
                        win32print.WritePrinter(h, full_bytes)
                        win32print.EndPagePrinter(h)
                    finally:
                        win32print.EndDocPrinter(h)
                finally:
                    win32print.ClosePrinter(h)
            else:
                subprocess.run(
                    ["lp", "-d", self.printer_name, "-o", "raw"],
                    input=full_bytes,
                    check=True,
                    capture_output=True,
                )
            on_progress(total_segs, total_bytes)
            return {
                "status": "completed",
                "printed_segment_index": total_segs,
                "printed_byte_offset": total_bytes,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error_message": f"OS spooler print error: {exc}",
                "printer_offline": True,
                "printed_segment_index": 0,
                "printed_byte_offset": 0,
            }


def build_transport() -> BaseTransport:
    mode = os.environ.get("PRINTER_MODE", "network_escpos").strip().lower()
    if mode == "serial":
        return SerialEscPosTransport(
            port=os.environ.get("SERIAL_PORT", "COM3"),
            baudrate=int(os.environ.get("SERIAL_BAUDRATE", "9600")),
        )
    if mode == "os_spooler":
        return OsSpoolerTransport(printer_name=os.environ.get("OS_PRINTER_NAME", "POS-80"))
    return NetworkEscPosTransport(
        host=os.environ.get("PRINTER_HOST", "192.168.1.200"),
        port=int(os.environ.get("PRINTER_PORT", "9100")),
    )


class SpoolStateStore:
    """Durable local recovery ledger so acknowledgements & checkpoints survive internet outages."""

    def __init__(self, path: Path):
        self.path = path
        self.pending_acks: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.pending_acks = list(data.get("pending_acks", []))
        except Exception:
            self.pending_acks = []

    def _save(self) -> None:
        self.path.write_text(json.dumps({"pending_acks": self.pending_acks}, indent=2), encoding="utf-8")

    def enqueue_ack(self, method_path: str, payload: dict[str, Any]) -> None:
        self.pending_acks.append({"path": method_path, "payload": payload})
        self._save()

    def flush(self, client: httpx.Client, headers: dict[str, str]) -> None:
        remaining: list[dict[str, Any]] = []
        for item in self.pending_acks:
            try:
                r = client.post(item["path"], headers=headers, json=item["payload"])
                if r.status_code >= 500:
                    remaining.append(item)
            except Exception:
                remaining.append(item)
        self.pending_acks = remaining
        self._save()


def run_agent_loop() -> None:
    api_base = os.environ["COLLEGEBITES_API_BASE"].rstrip("/")
    agent_id = os.environ["PRINT_AGENT_ID"].strip()
    agent_token = os.environ["PRINT_AGENT_TOKEN"].strip()
    poll_interval = max(1.0, float(os.environ.get("POLL_INTERVAL_SECONDS", "3.0")))
    state = SpoolStateStore(Path(os.environ.get("STATE_FILE", "agent_spool_state.json")))

    headers = {
        "X-Print-Agent-Id": agent_id,
        "X-Print-Agent-Token": agent_token,
        "Content-Type": "application/json",
    }
    transport = build_transport()
    log.info("Starting CollegeBites Print Agent (%s) against %s", agent_id, api_base)

    backoff = poll_interval
    with httpx.Client(base_url=api_base, timeout=15.0) as client:
        while True:
            try:
                # 1. Replay any local acks saved during a transient internet disconnect
                if state.pending_acks:
                    state.flush(client, headers)

                # 2. Probe physical kitchen printer & paper status
                probe = transport.probe()
                hb_res = client.post(
                    "/printing/agent/heartbeat",
                    headers=headers,
                    json={
                        "is_connected": probe.is_connected,
                        "is_online": probe.is_online,
                        "paper_status": probe.paper_status,
                        "supports_realtime_status": probe.supports_realtime_status,
                        "supports_resume_offset": probe.supports_resume_offset,
                        "last_error": probe.last_error,
                    },
                )
                hb_res.raise_for_status()
                backoff = poll_interval

                if not (probe.is_connected and probe.is_online) or probe.paper_status == "out_of_paper":
                    time.sleep(poll_interval)
                    continue

                # 3. Claim next pending/resumable receipt job in strict FIFO order
                while True:
                    claim_res = client.post("/printing/agent/jobs/claim", headers=headers)
                    claim_res.raise_for_status()
                    data = claim_res.json()
                    if not data.get("claimed"):
                        break

                    job_id = data["job"]["id"]
                    order_no = data["order_number"]
                    start_idx = int(data.get("resume_from_segment_index", 0))
                    segments = data["segments"]
                    log.info(
                        "Printing kitchen copy of customer receipt %s (job=%s, start_segment=%d/%d)",
                        order_no,
                        job_id,
                        start_idx,
                        len(segments),
                    )

                    def _on_progress(seg_idx: int, byte_off: int) -> None:
                        try:
                            client.post(
                                f"/printing/agent/jobs/{job_id}/progress",
                                headers=headers,
                                json={
                                    "printed_segment_index": seg_idx,
                                    "printed_byte_offset": byte_off,
                                    "supports_resume_offset": transport.supports_resume_offset,
                                },
                            )
                        except Exception:
                            pass

                    result = transport.send_segments(segments, start_idx, _on_progress)
                    if result["status"] == "completed":
                        ack_path = f"/printing/agent/jobs/{job_id}/complete"
                        ack_body = {
                            "printed_segment_index": result["printed_segment_index"],
                            "printed_byte_offset": result["printed_byte_offset"],
                        }
                        try:
                            client.post(ack_path, headers=headers, json=ack_body).raise_for_status()
                        except Exception:
                            state.enqueue_ack(ack_path, ack_body)
                        log.info("Completed receipt %s cleanly.", order_no)
                    elif result["status"] == "paused":
                        pause_path = f"/printing/agent/jobs/{job_id}/pause"
                        pause_body = {
                            "reason": result.get("reason", "out_of_paper"),
                            "paper_status": result.get("paper_status", "out_of_paper"),
                            "printed_segment_index": result["printed_segment_index"],
                            "printed_byte_offset": result["printed_byte_offset"],
                            "supports_resume_offset": transport.supports_resume_offset,
                            "is_connected": True,
                            "is_online": False,
                        }
                        try:
                            client.post(pause_path, headers=headers, json=pause_body).raise_for_status()
                        except Exception:
                            state.enqueue_ack(pause_path, pause_body)
                        log.warning(
                            "Paper roll empty on receipt %s; paused safely at segment %d (byte %d). Waiting for new paper roll...",
                            order_no,
                            result["printed_segment_index"],
                            result["printed_byte_offset"],
                        )
                        break
                    else:
                        fail_path = f"/printing/agent/jobs/{job_id}/fail"
                        fail_body = {
                            "error_message": result.get("error_message", "Printer transmission failed"),
                            "printer_offline": bool(result.get("printer_offline", True)),
                            "retry_delay_seconds": 10,
                            "printed_segment_index": result.get("printed_segment_index", start_idx),
                            "printed_byte_offset": result.get("printed_byte_offset", 0),
                        }
                        try:
                            client.post(fail_path, headers=headers, json=fail_body).raise_for_status()
                        except Exception:
                            state.enqueue_ack(fail_path, fail_body)
                        log.error("Print interrupted for %s; queued for safe retry.", order_no)
                        break

                time.sleep(poll_interval)
            except KeyboardInterrupt:
                log.info("Stopping CollegeBites Print Agent cleanly.")
                sys.exit(0)
            except Exception as exc:
                log.warning("Backend/network poll error: %s (retrying in %.1fs)", exc, backoff)
                time.sleep(backoff)
                backoff = min(30.0, backoff * 1.5)


if __name__ == "__main__":
    run_agent_loop()
