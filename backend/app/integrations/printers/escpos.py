import socket
from decimal import Decimal
from typing import Any

ESC = b"\x1b"
GS = b"\x1d"


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


def build_escpos_receipt_bytes(snapshot: dict[str, Any], paper_width: str = "80mm", is_reprint: bool = False, reprint_number: int = 0) -> bytes:
    """Generate complete ESC/POS thermal receipt bytes for 58mm (32 cols) or 80mm (48 cols) printers."""
    cols = 32 if paper_width == "58mm" else 48
    sep = ("-" * cols + "\n").encode("ascii")

    buf = bytearray()
    buf += ESC + b"@"  # Initialize
    buf += ESC + b"a\x01"  # Center align
    buf += ESC + b"E\x01"  # Bold ON
    buf += _line("COLLEGEBITES", cols)
    buf += _line(snapshot.get("college_name", "ACE ENGINEERING COLLEGE").upper(), cols)
    buf += _line(snapshot.get("canteen_name", "MAIN CANTEEN").upper(), cols)
    buf += ESC + b"E\x00"
    if snapshot.get("canteen_location"):
        buf += _line(snapshot["canteen_location"], cols)
    if is_reprint or reprint_number > 0:
        buf += ESC + b"E\x01"
        buf += _line(f"*** REPRINT #{max(1, reprint_number)} ***", cols)
        buf += ESC + b"E\x00"
    buf += sep

    buf += ESC + b"a\x00"  # Left align
    buf += _line(f"ORDER NO: {snapshot['order_number']}", cols)
    buf += ESC + b"a\x01"
    buf += _line("PICKUP TOKEN", cols)
    buf += GS + b"!\x11"  # Double width + double height
    buf += ESC + b"E\x01"
    buf += _line(snapshot["pickup_token"], cols)
    buf += GS + b"!\x00"
    buf += ESC + b"E\x00"
    buf += _escpos_qr_command(snapshot["qr_payload"], module_size=5 if paper_width == "58mm" else 6)
    buf += _line("", cols)
    buf += sep

    buf += ESC + b"a\x00"
    buf += _line(f"CUSTOMER: {snapshot.get('customer_name') or 'Guest'} ({snapshot.get('customer_type_label', 'Guest')})", cols)
    if snapshot.get("customer_mobile_masked"):
        buf += _line(f"MOBILE: {snapshot['customer_mobile_masked']}", cols)
    buf += _line(f"DATE: {snapshot['order_date']}  TIME: {snapshot['order_time']}", cols)
    buf += _line(f"COUNTER: {snapshot['counter_name']}", cols)
    buf += _line(f"TYPE: {snapshot['order_type'].upper()}  EST: {snapshot['estimated_pickup_time']}", cols)
    buf += sep

    buf += ESC + b"E\x01"
    buf += _line("ORDERED ITEMS", cols)
    buf += ESC + b"E\x00"
    for idx, item in enumerate(snapshot.get("items", []), start=1):
        variant_txt = f" ({item['variant_name']})" if item.get("variant_name") else ""
        buf += _line(f"{idx}. {item['item_name']}{variant_txt}", cols)
        buf += _lr(f"   {item['quantity']} x Rs.{Decimal(str(item['unit_price'])):.2f}", f"Rs.{Decimal(str(item['line_subtotal'])):.2f}", cols)
        for cust in item.get("customizations", []):
            if cust.get("customization_type") == "addon" and Decimal(str(cust.get("total_price", "0"))) > 0:
                buf += _lr(f"   + {cust['option_name']} {cust['option_value']}", f"Rs.{Decimal(str(cust['total_price'])):.2f}", cols)
            else:
                buf += _line(f"   - {cust['option_name']}: {cust['option_value']}", cols)
        if item.get("special_instructions"):
            buf += _line(f"   Note: {item['special_instructions']}", cols)

    buf += sep
    buf += _lr("SUBTOTAL:", f"Rs.{Decimal(str(snapshot['subtotal_amount'])):.2f}", cols)
    buf += _lr("DISCOUNT:", f"Rs.{Decimal(str(snapshot['discount_amount'])):.2f}", cols)
    buf += _lr("TAX:", f"Rs.{Decimal(str(snapshot['tax_amount'])):.2f}", cols)
    buf += ESC + b"E\x01"
    buf += _lr("TOTAL PAID:", f"Rs.{Decimal(str(snapshot['total_paid'])):.2f}", cols)
    buf += ESC + b"E\x00"
    buf += _line(f"PAY REF: {snapshot.get('payment_reference') or 'N/A'}", cols)
    buf += _line(f"PAY METHOD: {snapshot.get('payment_method', '').upper()} ({snapshot.get('payment_status')})", cols)
    buf += sep

    buf += ESC + b"a\x01"
    buf += _line(f"STATUS: {snapshot.get('order_status', 'CONFIRMED')}", cols)
    buf += _line(f"PICKUP: {snapshot['canteen_name']} / {snapshot['counter_name']}", cols)
    for instr in snapshot.get("pickup_instructions", []):
        buf += _line(instr, cols)
    buf += _line("THANK YOU FOR ORDERING!", cols)
    buf += b"\n\n\n"
    buf += GS + b"V\x00"  # Partial/full cut
    return bytes(buf)


def send_escpos_network_tcp(host: str, port: int, data: bytes, timeout_seconds: float = 3.0) -> None:
    """Send ESC/POS bytes to a TCP/IP thermal printer on port 9100."""
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.sendall(data)


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
