/**
 * Shared API contracts between the FastAPI backend, Customer/Staff Web app, and Expo Mobile app.
 * Every type mirrors the authoritative FastAPI Pydantic schemas in backend/app/schemas/.
 */

export type OrderStatus =
  | "CREATED"
  | "PAYMENT_PENDING"
  | "PAYMENT_CONFIRMED"
  | "PLACED"
  | "ACCEPTED"
  | "PREPARING"
  | "READY"
  | "COMPLETED"
  | "CANCELLED"
  | "REJECTED"
  | "PAYMENT_FAILED";

export type PaymentStatus = "PENDING" | "CONFIRMED" | "FAILED";
export type PaymentMethod = "razorpay" | "stripe" | "cash" | "pay_at_pickup" | "card_pos" | "upi_pos";

export interface CollegeSettingsDto {
  id: string;
  college_name: string;
  college_short_code?: string | null;
  logo_url?: string | null;
  address?: string | null;
  contact_phone?: string | null;
  contact_email?: string | null;
  default_tax_rate_percent: string;
  currency_code: string;
  currency_symbol: string;
  cancellation_policy_text: string;
  kiosk_enabled: boolean;
  guest_otp_required: boolean;
  razorpay_enabled: boolean;
  stripe_enabled: boolean;
  cash_at_counter_enabled: boolean;
  pay_at_pickup_enabled: boolean;
  college_timezone: string;
}

export interface CanteenDto {
  id: string;
  name: string;
  slug: string;
  code: string;
  token_prefix: string;
  description?: string | null;
  location?: string | null;
  canteen_type: string;
  is_active: boolean;
  is_temporarily_closed: boolean;
  closure_reason?: string | null;
  ordering_paused: boolean;
  pause_reason?: string | null;
  tax_rate_percent?: string | null;
  allow_online_payment: boolean;
  allow_cash_at_counter: boolean;
  allow_pay_at_pickup: boolean;
  is_open_now: boolean;
  crowd_level: string;
  estimated_wait_minutes: number;
  active_order_count: number;
}

export interface FoodVariantDto {
  id: string;
  name: string;
  price_delta: string;
  absolute_price?: string | null;
  is_default: boolean;
  is_available: boolean;
}

export interface FoodAddonDto {
  id: string;
  name: string;
  addon_type: string;
  price: string;
  is_veg: boolean;
  is_available: boolean;
  max_quantity: number;
}

export interface FoodItemDto {
  id: string;
  canteen_id: string;
  category_id: string;
  category_name?: string | null;
  name: string;
  slug: string;
  description?: string | null;
  base_price: string;
  is_veg: boolean;
  is_featured: boolean;
  is_popular: boolean;
  is_todays_special: boolean;
  is_recommended: boolean;
  prep_time_minutes: number;
  portion_size?: string | null;
  calories?: number | null;
  spice_levels: string[];
  sugar_levels: string[];
  removable_ingredients: string[];
  ingredients_text?: string | null;
  average_rating: number;
  rating_count: number;
  is_available: boolean;
  is_active: boolean;
  insufficient_ingredients: boolean;
  is_schedule_active_now?: boolean;
  images: Array<{ id: string; image_url: string; is_primary: boolean }>;
  variants: FoodVariantDto[];
  addons: FoodAddonDto[];
  allergens: Array<{ id: string; name: string }>;
}

export const COLLEGEBITES_API_PATHS = {
  college: "/canteens/college",
  canteens: "/canteens",
  login: "/auth/login",
  register: "/auth/register",
  otpRequest: "/auth/otp/request",
  otpVerify: "/auth/otp/verify",
  otpLogin: "/auth/otp/login",
  me: "/auth/me",
  logout: "/auth/logout",
  cart: "/carts",
  checkout: "/orders/checkout",
  myOrders: "/orders/my",
  razorpayVerify: "/payments/razorpay/verify",
  stripeVerify: "/payments/stripe/verify",
  notificationsMy: "/notifications/my",
  profile: "/customers/profile",
} as const;
