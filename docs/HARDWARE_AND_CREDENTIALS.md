# External Credentials & Hardware Dependencies

Per strict engineering honesty rules, the following features include complete integration code and **require real external credentials or physical hardware before certifying live production operation**:

1. **Razorpay Live Payments (`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`)**
   - Razorpay is the **sole** online payment gateway supported by CollegeBites.
   - Backend independently verifies HMAC-SHA256 payment signatures, fetches/validates payment status, amount (exact paise), and currency (`INR`) with Razorpay, and processes `X-Razorpay-Signature` webhooks (`payment.captured`, `order.paid`, `payment.failed`) idempotently.
   - Live production operation requires setting `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` on the backend server and registering `POST /api/v1/payments/razorpay/webhook` in the Razorpay Dashboard.

2. **Live Transactional OTP Providers (`OTP_*`, `SMTP_*`, `RESEND_API_KEY`, `SENDGRID_API_KEY`, `TWILIO_*`)**
   - OTP codes are cryptographically random 6-digit codes stored strictly as HMAC-SHA256 hashes (`otp_hash`) with 300s expiry, 60s resend cooldown, 5 max attempts, single-use consumption, and destination/IP/account rate limits.
   - Plaintext OTPs are never logged and never returned in API responses (`dev_otp` removed).
   - Real external delivery requires configuring `SMTP_HOST`/`SMTP_USERNAME`/`SMTP_PASSWORD`, `RESEND_API_KEY`, or `SENDGRID_API_KEY` for Email OTP, and `OTP_SMS_ENABLED=true` + Twilio/Webhook + Indian DLT compliance for SMS OTP. When unconfigured, `/api/v1/auth/otp/request` honestly returns HTTP `503 Service Unavailable`.

3. **Thermal Printers (58mm / 80mm ESC/POS)**
   - Customer digital receipts and customer `ReceiptPrintJob` records are generated automatically after verified payment confirmation; Kitchen Order Tickets (`kot` print jobs and ESC/POS payloads) are generated **only after** the order is accepted (`ACCEPTED`+) by kitchen staff.
   - Direct USB/Serial printing requires browser WebUSB/WebSerial permissions and compatible ESC/POS hardware; Network TCP/IP printing (`port 9100`) requires an accessible LAN thermal printer (`NETWORK_PRINTER_ENABLED=true`).

4. **Mobile Push & Camera Scanning**
   - Android & iOS builds (`mobile/`) use `expo-camera` and `expo-notifications`, which must be verified on physical Android/iOS devices with camera and notification permissions granted.

5. **Self-Service Touch Kiosk**
   - Disabled by default (`college_settings.kiosk_enabled = false`, `kiosk_devices.is_enabled = false`) until the college installs kiosk hardware and enables it in Admin Console.
