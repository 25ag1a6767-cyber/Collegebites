import base64
import hashlib
import socket
from decimal import Decimal
from typing import Any

ESC = b"\x1b"
GS = b"\x1d"
DLE_EOT_PRINTER = b"\x10\x04\x01"
DLE_EOT_OFFLINE = b"\x10\x04\x02"
DLE_EOT_PAPER = b"\x10\x04\x04"


def _wrap_lines(text: str, width: int) -> list[str]:
    text = text.strip()
    if len(text) <= width:
        return [text]
    lines: list[str] = []
    cur = ""
    for word in text.split(" "):
        if len(word) > width:
            if cur:
                lines.append(cur)
                cur = ""
            while len(word) > width:
                lines.append(word[:width])
                word = word[width:]
            cur = word
        elif not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur = f"{cur} {word}"
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _line(text: str, width: int) -> bytes:
    if not text:
        return b"\n"
    return b"".join((part + "\n").encode("ascii", errors="replace") for part in _wrap_lines(text, width))


def _lr(left: str, right: str, width: int) -> bytes:
    space = max(1, width - len(left) - len(right))
    if len(left) + len(right) + 1 > width:
        left = left[: max(1, width - len(right) - 1)]
    return (f"{left}{' ' * space}{right}\n").encode("ascii", errors="replace")


def _escpos_qr_command(data: str, module_size: int = 6) -> bytes:
    """Build standard ESC/POS GS ( k QR Code commands supported by 58mm/80mm thermal printers."""
    payload = data.encode("utf-8")
    store_len = len(payload) + 3
    pL = store_len & 0xFF
    pH = (store_len >> 8) & 0xFF
    return b"".join([
        GS + b"(k\x04\x00\x31\x41\x32\x00",  # Model 2
        GS + b"(k\x03\x00\x31\x43" + bytes([max(3, min(8, module_size))]),  # Module size
        GS + b"(k\x03\x00\x31\x45\x31",  # Error correction M
        GS + b"(k" + bytes([pL, pH]) + b"\x31\x50\x30" + payload,  # Store QR data
        GS + b"(k\x03\x00\x31\x51\x30",  # Print QR
    ])


def build_escpos_receipt_segments(
    snapshot: dict[str, Any],
    paper_width: str = "80mm",
    is_reprint: bool = False,
    reprint_number: int = 0,
) -> list[dict[str, Any]]:
    """
    Build deterministic ordered ESC/POS segments from the SINGLE canonical `receipt_snapshot`.
    Both customer and kitchen printing use this exact segmented document so branding, items,
    totals, payment details, and the original customer QR code are 100% identical, while allowing
    exact segment/byte-offset resumption if the thermal roll finishes mid-receipt.
    """
    cols = 32 if paper_width == "58mm" else 48
    sep = ("-" * cols + "\n").encode("ascii")

    raw_segments: list[tuple[str, bytes]] = []

    # Segment 0: Header branding & location
    b0 = bytearray()
    b0 += ESC + b"@"  # Initialize
    b0 += ESC + b"a\x01"  # Center align
    b0 += ESC + b"E\x01"  # Bold ON
    b0 += _line(snapshot.get("brand", "COLLEGEBITES"), cols)
    b0 += _line(snapshot.get("college_name", "ACE ENGINEERING COLLEGE").upper(), cols)
    b0 += _line(snapshot.get("canteen_name", "MAIN CANTEEN").upper(), cols)
    b0 += ESC + b"E\x00"
    if snapshot.get("canteen_location"):
        b0 += _line(snapshot["canteen_location"], cols)
    if is_reprint or reprint_number > 0:
        b0 += ESC + b"E\x01"
        b0 += _line(f"*** REPRINT #{max(1, reprint_number)} ***", cols)
        b0 += ESC + b"E\x00"
    b0 += sep
    raw_segments.append(("header_branding", bytes(b0)))

    # Segment 1: Order number, Pickup Token & Identical Customer QR Code
    b1 = bytearray()
    b1 += ESC + b"a\x00"  # Left align
    b1 += _line(f"ORDER NO: {snapshot['order_number']}  REC: {snapshot.get('receipt_number', '')}", cols)
    b1 += ESC + b"a\x01"
    b1 += _line("PICKUP TOKEN", cols)
    b1 += GS + b"!\x11"  # Double width + double height
    b1 += ESC + b"E\x01"
    b1 += _line(snapshot["pickup_token"], cols)
    b1 += GS + b"!\x00"
    b1 += ESC + b"E\x00"
    b1 += _escpos_qr_command(snapshot["qr_payload"], module_size=5 if paper_width == "58mm" else 6)
    b1 += _line("", cols)
    b1 += sep
    raw_segments.append(("order_and_qr", bytes(b1)))

    # Segment 2: Customer, Date/Time & Counter Info
    b2 = bytearray()
    b2 += ESC + b"a\x00"
    b2 += _line(f"CUSTOMER: {snapshot.get('customer_name') or 'Guest'} ({snapshot.get('customer_type_label', 'Guest')})", cols)
    if snapshot.get("customer_mobile_masked"):
        b2 += _line(f"MOBILE: {snapshot['customer_mobile_masked']}", cols)
    b2 += _line(f"DATE: {snapshot['order_date']}  TIME: {snapshot['order_time']}", cols)
    b2 += _line(f"COUNTER: {snapshot['counter_name']}", cols)
    b2 += _line(f"TYPE: {snapshot['order_type'].upper()}  EST: {snapshot['estimated_pickup_time']}", cols)
    b2 += sep
    raw_segments.append(("customer_datetime", bytes(b2)))

    # Segment 3: Items Header
    b3 = bytearray()
    b3 += ESC + b"a\x00"
    b3 += ESC + b"E\x01"
    b3 += _line("ORDERED ITEMS", cols)
    b3 += ESC + b"E\x00"
    raw_segments.append(("items_header", bytes(b3)))

    # Segments 4..N: Individual Line Items (clean checkpoint boundary per item)
    for idx, item in enumerate(snapshot.get("items", []), start=1):
        bi = bytearray()
        bi += ESC + b"a\x00"
        variant_txt = f" ({item['variant_name']})" if item.get("variant_name") else ""
        bi += _line(f"{idx}. {item['item_name']}{variant_txt}", cols)
        bi += _lr(
            f"   {item['quantity']} x Rs.{Decimal(str(item['unit_price'])):.2f}",
            f"Rs.{Decimal(str(item['line_subtotal'])):.2f}",
            cols,
        )
        for cust in item.get("customizations", []):
            if cust.get("customization_type") == "addon" and Decimal(str(cust.get("total_price", "0"))) > 0:
                bi += _lr(
                    f"   + {cust['option_name']} {cust['option_value']}",
                    f"Rs.{Decimal(str(cust['total_price'])):.2f}",
                    cols,
                )
            else:
                bi += _line(f"   - {cust['option_name']}: {cust['option_value']}", cols)
        if item.get("special_instructions"):
            bi += _line(f"   Note: {item['special_instructions']}", cols)
        raw_segments.append((f"item_{idx}", bytes(bi)))

    # Segment N+1: Totals & Payment Confirmation Info
    bt = bytearray()
    bt += ESC + b"a\x00"
    bt += sep
    bt += _lr("SUBTOTAL:", f"Rs.{Decimal(str(snapshot['subtotal_amount'])):.2f}", cols)
    if Decimal(str(snapshot.get("discount_amount", "0.00"))) > Decimal("0.00"):
        bt += _lr("DISCOUNT:", f"-Rs.{Decimal(str(snapshot['discount_amount'])):.2f}", cols)
    if Decimal(str(snapshot.get("tax_amount", "0.00"))) > Decimal("0.00"):
        bt += _lr("TAX:", f"Rs.{Decimal(str(snapshot['tax_amount'])):.2f}", cols)
    bt += ESC + b"E\x01"
    bt += _lr("TOTAL PAID:", f"Rs.{Decimal(str(snapshot['total_paid'])):.2f}", cols)
    bt += ESC + b"E\x00"
    if Decimal(str(snapshot.get("tax_amount", "0.00"))) == Decimal("0.00"):
        bt += _line("Prices incl. applicable statutory taxes", cols)
    bt += _line(f"PAY REF: {snapshot.get('payment_reference') or 'N/A'}", cols)
    bt += _line(f"PAY METHOD: {snapshot.get('payment_method', '').upper()} ({snapshot.get('payment_status')})", cols)
    bt += sep
    raw_segments.append(("totals_payment", bytes(bt)))

    # Segment N+2: Pickup Instructions & Partial/Full Paper Cut
    bf = bytearray()
    bf += ESC + b"a\x01"
    bf += _line(f"STATUS: {snapshot.get('order_status', 'CONFIRMED')}", cols)
    bf += _line(f"PICKUP: {snapshot['canteen_name']} / {snapshot['counter_name']}", cols)
    for instr in snapshot.get("pickup_instructions", []):
        bf += _line(instr, cols)
    bf += _line("THANK YOU FOR ORDERING!", cols)
    bf += b"\n\n\n"
    bf += GS + b"V\x00"
    raw_segments.append(("footer_and_cut", bytes(bf)))

    out: list[dict[str, Any]] = []
    offset = 0
    for idx, (seg_name, seg_bytes) in enumerate(raw_segments):
        blen = len(seg_bytes)
        out.append({
            "index": idx,
            "name": seg_name,
            "byte_start": offset,
            "byte_end": offset + blen,
            "byte_length": blen,
            "bytes": seg_bytes,
            "base64_bytes": base64.b64encode(seg_bytes).decode("ascii"),
        })
        offset += blen
    return out


def compute_escpos_checksum(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def build_escpos_receipt_bytes(
    snapshot: dict[str, Any],
    paper_width: str = "80mm",
    is_reprint: bool = False,
    reprint_number: int = 0,
) -> bytes:
    """Generate complete ESC/POS thermal receipt bytes for 58mm (32 cols) or 80mm (48 cols) printers."""
    segments = build_escpos_receipt_segments(
        snapshot,
        paper_width=paper_width,
        is_reprint=is_reprint,
        reprint_number=reprint_number,
    )
    return b"".join(seg["bytes"] for seg in segments)


def parse_escpos_realtime_status(status_byte: int | None, offline_byte: int | None, paper_byte: int | None) -> dict[str, Any]:
    """Decode ESC/POS DLE EOT real-time status bytes (online, cover/error, paper availability)."""
    is_online = True if status_byte is None else not bool(status_byte & 0x08)
    cover_open_or_err = False if offline_byte is None else bool(offline_byte & 0x64)
    paper_out = False if paper_byte is None else bool(paper_byte & 0x60)
    paper_low = False if paper_byte is None else bool(paper_byte & 0x0C)

    if paper_out:
        paper_status = "out_of_paper"
        is_online = False
    elif paper_low:
        paper_status = "low"
    elif paper_byte is not None:
        paper_status = "available"
    else:
        paper_status = "unknown"

    return {
        "is_connected": True,
        "is_online": bool(is_online and not cover_open_or_err and not paper_out),
        "paper_status": paper_status,
        "cover_open_or_error": cover_open_or_err,
    }


def query_escpos_tcp_status(host: str, port: int, timeout_seconds: float = 1.5) -> dict[str, Any]:
    """Query DLE EOT 1/2/4 real-time printer & paper status over TCP/9100."""
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.settimeout(timeout_seconds)

        def _ask(cmd: bytes) -> int | None:
            sock.sendall(cmd)
            try:
                resp = sock.recv(1)
                return resp[0] if resp else None
            except socket.timeout:
                return None

        b1 = _ask(DLE_EOT_PRINTER)
        b2 = _ask(DLE_EOT_OFFLINE)
        b4 = _ask(DLE_EOT_PAPER)
        return parse_escpos_realtime_status(b1, b2, b4)


def send_escpos_network_tcp(host: str, port: int, data: bytes, timeout_seconds: float = 3.0) -> None:
    """Send ESC/POS bytes to a TCP/IP thermal printer on port 9100."""
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.sendall(data)


def send_escpos_segments_tcp(
    host: str,
    port: int,
    segments: list[dict[str, Any]],
    start_segment_index: int = 0,
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    """
    Stream ESC/POS receipt segments over TCP/9100 starting at `start_segment_index`.
    Checks paper/online readiness between segments when printer responds to DLE EOT 4.
    If paper runs out mid-receipt, stops cleanly before the next unprinted segment and
    returns exact resume offsets so nothing is lost or duplicated when paper is reloaded.
    """
    if start_segment_index >= len(segments):
        total_bytes = segments[-1]["byte_end"] if segments else 0
        return {
            "status": "completed",
            "printed_segment_index": len(segments),
            "printed_byte_offset": total_bytes,
        }

    printed_idx = start_segment_index
    printed_bytes = segments[start_segment_index - 1]["byte_end"] if start_segment_index > 0 else 0
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.settimeout(timeout_seconds)
        for seg in segments[start_segment_index:]:
            # Query paper status before sending segment when printer supports DLE EOT 4
            sock.sendall(DLE_EOT_PAPER)
            try:
                p_resp = sock.recv(1)
                if p_resp and (p_resp[0] & 0x60):
                    return {
                        "status": "paused",
                        "paused_reason": "out_of_paper",
                        "paper_status": "out_of_paper",
                        "printed_segment_index": printed_idx,
                        "printed_byte_offset": printed_bytes,
                    }
            except socket.timeout:
                pass

            sock.sendall(seg["bytes"])
            printed_idx = seg["index"] + 1
            printed_bytes = seg["byte_end"]

    return {
        "status": "completed",
        "printed_segment_index": printed_idx,
        "printed_byte_offset": printed_bytes,
    }


def build_escpos_kot_bytes(kot: dict[str, Any], paper_width: str = "80mm") -> bytes:
    """Generate compact ESC/POS Kitchen Order Ticket (KOT) bytes for prep stations."""
    cols = 32 if paper_width == "58mm" else 48
    sep = ("=" * cols + "\n").encode("ascii")

    buf = bytearray()
    buf += ESC + b"@"
    buf += ESC + b"a\x01"
    buf += ESC + b"E\x01"
    buf += _line("KITCHEN ORDER TICKET (KOT)", cols)
    if kot.get("is_priority"):
        buf += _line("*** RUSH / PRIORITY ORDER ***", cols)
    buf += GS + b"!\x11"
    buf += _line(f"TOKEN: {kot['pickup_token']}", cols)
    buf += GS + b"!\x00"
    buf += ESC + b"E\x00"
    buf += sep

    buf += ESC + b"a\x00"
    buf += _line(f"ORDER: {kot['order_number']}", cols)
    buf += _line(f"CANTEEN: {kot.get('canteen_name', '')}", cols)
    if kot.get("counter_name"):
        buf += _line(f"COUNTER: {kot['counter_name']}  TYPE: {kot.get('order_type', 'pickup').upper()}", cols)
    if kot.get("station_filter_name"):
        buf += _line(f"STATION: {kot['station_filter_name']}", cols)
    buf += _line(f"TIME: {kot.get('order_time', '')}", cols)
    buf += sep

    buf += ESC + b"E\x01"
    buf += _line("PREP ITEMS", cols)
    buf += ESC + b"E\x00"
    for item in kot.get("items", []):
        st_lbl = f" [{item['station_name']}]" if item.get("station_name") else ""
        var_lbl = f" ({item['variant_name']})" if item.get("variant_name") else ""
        buf += _line(f"{item['quantity']}x {item['item_name']}{var_lbl}{st_lbl}", cols)
        for cust in item.get("customizations", []):
            buf += _line(f"   - {cust['option_name']}: {cust['option_value']}", cols)
        if item.get("special_instructions"):
            buf += _line(f"   NOTE: {item['special_instructions']}", cols)
    if kot.get("notes"):
        buf += sep
        buf += _line(f"ORDER NOTE: {kot['notes']}", cols)
    buf += b"\n\n\n"
    buf += GS + b"V\x00"
    return bytes(buf)
