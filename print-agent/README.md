# CollegeBites Local Kitchen Thermal Print Agent

Secure local service running on the physical kitchen PC/Raspberry Pi to bridge cloud-verified CollegeBites orders (`collegebites-smart-campus.vercel.app`) to the physical thermal printer (USB/Serial, Windows/CUPS OS Spooler, or LAN ESC/POS port 9100).

## Features
- Authenticates strictly via registered `X-Print-Agent-Id` + `X-Print-Agent-Token`.
- Prints the **exact same canonical customer receipt** (CollegeBites branding, items, prices, totals, payment info, and original customer QR code) automatically without manual staff action.
- Polls ESC/POS `DLE EOT 1/2/4` real-time printer & paper-roll sensors between receipt segments.
- **Paper-Roll Continuation:** If the thermal roll finishes mid-receipt, pauses immediately at the exact segment/byte offset, alerts the Kitchen Printer Recovery Dashboard, waits until a new roll is loaded, and automatically prints only the remaining segments without duplicating already printed content.
- **Crash/Disconnect Resilience:** Buffers unacknowledged completions/pause offsets in `agent_spool_state.json` and syncs automatically on reconnect.

## Quick Setup
```bash
cd print-agent
python -m venv .venv
# Windows: .venv\Scripts\activate  |  Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 1. Register your kitchen printer in Kitchen Display -> "Printer & Auto-Print"
# 2. Paste PRINT_AGENT_ID and PRINT_AGENT_TOKEN into .env
python print_agent.py
```
