# CollegeBites Mobile App & Shared Backend API Integration Guide

## 1. Shared Monorepo Topology

- **Shared FastAPI Backend & PostgreSQL (`backend/`)**: Authoritative business logic, server pricing, loyalty, Razorpay + Stripe signature & webhook verification, HMAC QR generation/verification, ReportLab PDFs, WebSockets, and audit logging.
- **Customer Web & Operations Portals (`frontend/`)**: Vite + React + TypeScript PWA (`manifest.webmanifest`, `sw.js`, bottom mobile app tab bar, `/scan` camera scanner, Kitchen Display, Cashier POS, Pickup Scanner, Digital Token Board, Inventory, Admin Console).
- **Customer & QR Mobile App (`mobile/`)**: Expo SDK 52 + React Native + Expo Router + TanStack Query + Zustand + React Hook Form + Zod + Expo SecureStore + Expo Camera + Expo Notifications + `@stripe/stripe-react-native` PaymentSheet.
- **Shared Contracts (`shared/api-contracts/collegebites.contracts.ts`)**: Shared DTO types and canonical `/api/v1/*` path definitions.

## 2. Mobile API Module Mapping (`mobile/src/api/`)

| Mobile Module | Backend Routes Consumed | Purpose |
|---|---|---|
| `client.ts` | `/api/v1/auth/refresh`, `/ws/*` | Axios instance, single-flight 401 refresh mutex, guest session header, WebSocket URL builder |
| `auth.api.ts` | `POST /auth/login`, `/auth/register`, `/auth/otp/request`, `/auth/otp/verify`, `/auth/otp/login`, `/auth/password-reset/confirm`, `/auth/change-password`, `/auth/phone/verify`, `GET /auth/me`, `POST /auth/logout` | Universal account & guest OTP authentication |
| `canteens.api.ts` | `GET /canteens/college`, `/canteens`, `/canteens/{id}`, `/promotions`, `/notifications/announcements` | College settings, real canteen list/details/counters, active offers |
| `menu.api.ts` | `GET /menus/canteens/{id}/categories`, `/menus/canteens/{id}/items`, `GET /support/items/{id}/reviews`, `POST /support/reviews` | Menu catalog, search/filter/sort, customization variants/addons, reviews |
| `cart.api.ts` | `GET /carts`, `POST /carts/items`, `PATCH /carts/items/{id}` | Server-validated cart pricing and customizations |
| `orders.api.ts` | `GET /orders/slots/{canteen_id}`, `POST /orders/checkout`, `GET /orders/my`, `GET /orders/{id}`, `POST /orders/guest/lookup`, `POST /orders/{id}/cancel` | Idempotent checkout, loyalty redemption, slot reservation, guest OTP order recovery |
| `payments.api.ts` | `GET /payments/stripe/config`, `POST /payments/razorpay/{verify,fail}`, `POST /payments/stripe/{verify,fail}`, `POST /payments/retry/{order_id}` | Stripe PaymentSheet config & native/web gateway verification/failure handling (No-Refund compliant) |
| `tokens.api.ts` | `GET /qr/locations/resolve/{code}`, `GET /tokens/receipts/{order_no}`, `/tokens/receipts/{order_no}/pdf`, `POST /pickup/{verify,handover}`, `GET /pickup/board/{id}` | Table/counter QR resolve, token & QR receipt, PDF/Share, live token board |
| `notifications.api.ts` | `GET /notifications/my`, `POST /notifications/{id}/read`, `POST /notifications/mark-all-read`, `GET/PUT /notifications/preferences`, `POST /notifications/push-tokens` | Notification inbox, channel preferences, Expo Push token sync |
| `profile.api.ts` | `GET/PATCH /customers/profile`, `GET/POST/DELETE /customers/favourites`, `DELETE /customers/me`, `GET /promotions/loyalty/me`, `POST /promotions/loyalty/apply-referral`, `GET/POST /support/tickets*` | Profile/dietary edits, favourites, loyalty/referrals, self-deactivation, support tickets |

## 3. Running & Building Android / iOS

See [`mobile/README.md`](../mobile/README.md) for Expo Go, Android Emulator, iOS Simulator, `mobile/.env.example`, and EAS APK/AAB/IPA build profiles (`mobile/eas.json`).

## 4. External Credentials Still Required for Production Store & Gateway Release

1. **Expo / App Stores:** EAS account login + Android Play Console signing keystore + Apple Developer Program account (for physical iOS builds & APNs/FCM push delivery).
2. **Live Payment Gateways:** Production merchant keys in Vercel env (`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, with `RAZORPAY_TEST_MODE=false` / `STRIPE_TEST_MODE=false`).
3. **Production Security Switches:** Set `ENVIRONMENT=production` and `OTP_TEST_ECHO=false` once SMS/Email delivery credentials (`TWILIO_*` / `SMTP_*`) are configured.
