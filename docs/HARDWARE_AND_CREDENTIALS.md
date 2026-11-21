# External Credentials & Hardware Dependencies

Per strict engineering honesty rules, the following features include full integration code and local test modes, and **require real credentials or physical hardware before certifying live production operation**:

1. **Razorpay Live Payments (`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`)**
   - Local development & automated tests verify genuine HMAC-SHA256 signatures using test keys (`RAZORPAY_TEST_MODE=true`).
   - Live UPI/Card/Netbanking charges and real Razorpay webhook delivery require setting real Razorpay merchant credentials and registering `https://<domain>/api/v1/payments/razorpay/webhook` in the Razorpay Dashboard.

2. **Email / SMS / WhatsApp Providers (`SMTP_*`, `SMS_PROVIDER`, `WHATSAPP_PROVIDER`)**
   - OTP and order notifications dispatch via SMTP when `SMTP_HOST` is configured; otherwise messages are safely logged in server logs without failing orders.

3. **Thermal Printers (58mm / 80mm ESC/POS)**
   - Browser Print (`window.print()`), downloadable A4 / 80mm PDF (`ReportLab`), and raw ESC/POS binary byte generation (`GS ( k` QR + double-height token) are fully built and tested.
   - Direct USB/Serial printing requires browser WebUSB/WebSerial permissions and compatible ESC/POS hardware; Network TCP/IP printing (`port 9100`) requires an accessible LAN thermal printer (`NETWORK_PRINTER_ENABLED=true`).

4. **Mobile Push & Camera Scanning**
   - Android & iOS builds (`mobile/`) use `expo-camera` and `expo-notifications`, which must be verified on physical Android/iOS devices with camera and notification permissions granted.

5. **Self-Service Touch Kiosk**
   - Disabled by default (`college_settings.kiosk_enabled = false`, `kiosk_devices.is_enabled = false`) until the college installs kiosk hardware and enables it in Admin Console.
