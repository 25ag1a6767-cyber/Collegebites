# External Credentials & Hardware Dependencies

Per strict engineering honesty rules, the following features include full integration code and local test modes, and **require real credentials or physical hardware before certifying live production operation**:

1. **Razorpay & Stripe Live Payments (`RAZORPAY_*`, `STRIPE_*`)**
   - Local development & automated tests verify genuine HMAC-SHA256 signatures and mock/test-mode Stripe & Razorpay SDK flows (`RAZORPAY_TEST_MODE=true`, `STRIPE_TEST_MODE=true`).
   - Live charges and real webhook delivery require setting `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` and/or `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, plus registering `/api/v1/payments/razorpay/webhook` and `/api/v1/payments/stripe/webhook` in the merchant dashboards.
   - Native mobile Stripe PaymentSheet (`@stripe/stripe-react-native`) requires a custom Expo dev client / EAS native build rather than stock Expo Go.

2. **Email / SMS / WhatsApp Providers (`SMTP_*`, `SMS_PROVIDER`, `TWILIO_*`, `WHATSAPP_PROVIDER`)**
   - OTP and order notifications dispatch via SMTP when `SMTP_HOST` is configured; SMS OTP in production requires `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` (with `SMS_PROVIDER=twilio`) or `SMS_WEBHOOK_URL` (`SMS_PROVIDER=webhook`), returning HTTP `503` otherwise rather than faking delivery.

3. **Thermal Printers (58mm / 80mm ESC/POS)**
   - Browser Print (`window.print()`), downloadable A4 / 80mm PDF (`ReportLab`), and raw ESC/POS binary byte generation (`GS ( k` QR + double-height token) are fully built and tested.
   - Direct USB/Serial printing requires browser WebUSB/WebSerial permissions and compatible ESC/POS hardware; Network TCP/IP printing (`port 9100`) requires an accessible LAN thermal printer (`NETWORK_PRINTER_ENABLED=true`).

4. **Mobile Push & Camera Scanning**
   - Android & iOS builds (`mobile/`) use `expo-camera` and `expo-notifications`, which must be verified on physical Android/iOS devices with camera and notification permissions granted.

5. **Self-Service Touch Kiosk**
   - Disabled by default (`college_settings.kiosk_enabled = false`, `kiosk_devices.is_enabled = false`) until the college installs kiosk hardware and enables it in Admin Console.
