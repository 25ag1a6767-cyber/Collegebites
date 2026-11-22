# CollegeBites Mobile Application (Android & iOS — Expo React Native)

Shared-backend customer & QR mobile app for **CollegeBites**, connecting directly to the same FastAPI + PostgreSQL + Redis backend as the CollegeBites Web platform (`https://collegebites-alpha.vercel.app`).

## Architecture & Shared Backend Connection

- **API Client:** `src/api/client.ts` + typed modules (`auth.api.ts`, `canteens.api.ts`, `menu.api.ts`, `cart.api.ts`, `orders.api.ts`, `payments.api.ts`, `tokens.api.ts`, `notifications.api.ts`, `profile.api.ts`)
- **Base URL Resolution:**
  1. `process.env.EXPO_PUBLIC_API_URL` (override in `.env` for local LAN testing)
  2. `app.json` -> `expo.extra.apiUrl` (`https://collegebites-alpha.vercel.app/api/v1`)
- **Security:** JWT access & refresh tokens, guest session ID, and guest order tokens are stored via `expo-secure-store` (native iOS Keychain / Android Keystore) or Web storage when run on Expo Web. Single-flight refresh mutex prevents race conditions on 401 expiry.
- **No-Refund Compliance:** No refund buttons, endpoints, or balances exist anywhere in the app. Cancelled/failed orders preserve immutable transaction ledgers.

## Quick Setup & Running

```bash
cd mobile
cp .env.example .env
npm install

# Type-check & export bundles across Android, iOS, Web
npm run typecheck
npx expo export --platform all

# Run interactively
npm run start
npm run android   # Android Emulator or USB device via ADB
npm run ios       # iOS Simulator (macOS Xcode required)
npm run web       # Browser Expo Web
```

## Connecting a Physical Android / iOS Device

- **Production backend:** Works automatically using `expo.extra.apiUrl` (`https://collegebites-alpha.vercel.app/api/v1`). Scan the Metro QR code in Expo Go.
- **Local FastAPI backend:** Start FastAPI bound to `0.0.0.0:8000` (`uvicorn app.main:app --host 0.0.0.0 --port 8000`) and set `EXPO_PUBLIC_API_URL=http://<YOUR_LAN_IP>:8000/api/v1` in `mobile/.env`. Do NOT use `127.0.0.1` on a physical phone.

## Android APK / AAB & iOS IPA Builds (EAS)

Configured via `mobile/eas.json`:

```bash
# Install EAS CLI
npm install -g eas-cli
eas login

# Internal Android APK (direct sideload install for students/testers)
eas build -p android --profile preview

# Production Android AAB (Play Store) & iOS IPA (App Store / TestFlight)
eas build -p android --profile production
eas build -p ios --profile production
```

## Push Notifications, Deep Linking & Native Payments

- **Deep Linking:** `collegebites://` custom scheme + verified app links for `https://collegebites-alpha.vercel.app/scan/<code>` (`app/scan/[code].tsx`).
- **Push Notifications:** `src/notifications/registerPush.ts` registers Expo push tokens at `/api/v1/notifications/push-tokens` when running on physical devices with Expo project credentials (`eas project:init`).
- **Stripe PaymentSheet & Gateways:** Native Android/iOS uses `@stripe/stripe-react-native` (`src/components/StripePayButton.native.tsx`, configured in `app.json`) powered by `/api/v1/payments/stripe/config`; Expo Web uses `StripePayButton.web.tsx`. Native Stripe PaymentSheet requires an EAS / custom development build (`eas build --profile preview|development|production`) rather than stock Expo Go. Live production checkout requires approved Razorpay (`RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`/`RAZORPAY_WEBHOOK_SECRET`) or Stripe (`STRIPE_SECRET_KEY`/`STRIPE_PUBLISHABLE_KEY`/`STRIPE_WEBHOOK_SECRET`) environment variables on Vercel.
