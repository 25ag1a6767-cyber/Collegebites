export interface User {
  id: string;
  email?: string | null;
  phone?: string | null;
  full_name: string;
  user_kind: string;
  is_active: boolean;
  is_verified: boolean;
  roles: string[];
  permissions: string[];
  assigned_canteen_id?: string | null;
}

export interface CollegeSettings {
  id: string;
  college_name: string;
  college_short_code: string;
  logo_url?: string | null;
  address?: string | null;
  contact_phone?: string | null;
  contact_email?: string | null;
  default_tax_rate_percent: string;
  currency_symbol: string;
  cancellation_policy_text: string;
  kiosk_enabled: boolean;
  guest_otp_required: boolean;
  razorpay_enabled: boolean;
  cash_at_counter_enabled: boolean;
  pay_at_pickup_enabled: boolean;
}

export interface Counter {
  id: string;
  canteen_id: string;
  name: string;
  code: string;
  counter_type: string;
  is_active: boolean;
  max_queue_capacity: number;
}

export interface Kitchen {
  id: string;
  canteen_id: string;
  name: string;
  code: string;
  max_active_orders: number;
  is_active: boolean;
}

export interface DiningTable {
  id: string;
  canteen_id: string;
  counter_id?: string | null;
  table_number: string;
  zone_label?: string | null;
  capacity: number;
  is_active: boolean;
}

export interface Canteen {
  id: string;
  name: string;
  slug: string;
  code: string;
  token_prefix: string;
  description?: string | null;
  location: string;
  contact_phone?: string | null;
  canteen_type: string;
  is_active: boolean;
  is_temporarily_closed: boolean;
  ordering_paused: boolean;
  pause_reason?: string | null;
  tax_rate_percent: string;
  allow_online_payment: boolean;
  allow_cash_at_counter: boolean;
  allow_pay_at_pickup: boolean;
  max_concurrent_orders: number;
  default_prep_time_minutes: number;
  is_open_now: boolean;
  crowd_level: "LOW" | "MODERATE" | "HIGH" | "VERY_HIGH" | "TEMPORARILY_UNAVAILABLE";
  estimated_wait_minutes: number;
  active_order_count: number;
  counters?: Counter[];
  kitchens?: Kitchen[];
  tables?: DiningTable[];
}

export interface FoodCategory {
  id: string;
  canteen_id: string;
  name: string;
  slug: string;
  description?: string | null;
  display_order: number;
  is_active: boolean;
}

export interface FoodVariant {
  id: string;
  name: string;
  price_delta: string;
  absolute_price?: string | null;
  is_default: boolean;
  is_available: boolean;
}

export interface FoodAddon {
  id: string;
  name: string;
  addon_type: string;
  price: string;
  is_veg: boolean;
  is_available: boolean;
  max_quantity: number;
}

export interface FoodItem {
  id: string;
  canteen_id: string;
  category_id: string;
  category_name?: string | null;
  kitchen_id?: string | null;
  counter_id?: string | null;
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
  nutrition_info?: Record<string, unknown> | null;
  spice_levels: string[];
  sugar_levels: string[];
  removable_ingredients: string[];
  ingredients_text?: string | null;
  average_rating: string;
  rating_count: number;
  popularity_score: number;
  is_available: boolean;
  is_active: boolean;
  insufficient_ingredients: boolean;
  images: { id: string; image_url: string; alt_text?: string | null; is_primary: boolean }[];
  variants: FoodVariant[];
  addons: FoodAddon[];
  allergens: { id: string; name: string }[];
}

export interface CartSummary {
  cart_id?: string | null;
  canteen_id: string;
  canteen_name: string;
  coupon_code?: string | null;
  coupon_valid: boolean;
  coupon_message?: string | null;
  items: {
    id: string;
    food_item_id: string;
    item_name: string;
    variant_id?: string | null;
    variant_name?: string | null;
    quantity: number;
    unit_price: string;
    addon_total_per_unit: string;
    line_subtotal: string;
    special_instructions?: string | null;
    customizations: {
      customization_type: string;
      option_name: string;
      option_value: string;
      quantity: number;
      unit_price: string;
      total_price: string;
    }[];
  }[];
  subtotal_amount: string;
  discount_amount: string;
  tax_amount: string;
  total_amount: string;
  is_canteen_open: boolean;
  has_capacity: boolean;
  estimated_prep_minutes: number;
  validation_errors: string[];
}

export interface Order {
  id: string;
  order_number: string;
  canteen_id: string;
  canteen_name?: string | null;
  counter_id: string;
  counter_name?: string | null;
  is_guest: boolean;
  guest_name?: string | null;
  guest_phone_masked?: string | null;
  order_type: string;
  order_channel: string;
  status: string;
  payment_status: string;
  payment_method: string;
  subtotal_amount: string;
  discount_amount: string;
  tax_amount: string;
  total_amount: string;
  coupon_code?: string | null;
  estimated_prep_minutes: number;
  estimated_pickup_at?: string | null;
  delayed_minutes: number;
  delay_reason?: string | null;
  pickup_token_code?: string | null;
  qr_verification_path?: string | null;
  qr_token_raw?: string | null;
  guest_access_token?: string | null;
  razorpay_order_id?: string | null;
  razorpay_key_id?: string | null;
  cancellation_policy_text?: string | null;
  created_at: string;
  confirmed_at?: string | null;
  ready_at?: string | null;
  completed_at?: string | null;
  items: {
    id: string;
    food_item_id?: string | null;
    variant_id?: string | null;
    item_name: string;
    variant_name?: string | null;
    quantity: number;
    unit_price: string;
    line_subtotal: string;
    line_total: string;
    special_instructions?: string | null;
    customizations: {
      id: string;
      customization_type: string;
      option_name: string;
      option_value: string;
      quantity: number;
      unit_price: string;
      total_price: string;
    }[];
  }[];
  status_history: {
    id: string;
    from_status?: string | null;
    to_status: string;
    reason?: string | null;
    created_at: string;
  }[];
}

export interface ReceiptSnapshot {
  receipt_id: string;
  brand: string;
  college_name: string;
  college_short_code: string;
  college_logo_url?: string | null;
  canteen_name: string;
  canteen_location: string;
  canteen_contact?: string | null;
  counter_name: string;
  receipt_number: string;
  order_number: string;
  pickup_token: string;
  qr_payload: string;
  qr_image_base64: string;
  order_date: string;
  order_time: string;
  estimated_pickup_time: string;
  payment_reference: string;
  payment_method: string;
  payment_status: string;
  order_type: string;
  order_status: string;
  customer_name: string;
  customer_type_label: string;
  customer_mobile_masked?: string | null;
  items: {
    item_name: string;
    variant_name?: string | null;
    quantity: number;
    unit_price: string;
    line_subtotal: string;
    special_instructions?: string | null;
    customizations: {
      customization_type: string;
      option_name: string;
      option_value: string;
      quantity: number;
      unit_price: string;
      total_price: string;
    }[];
  }[];
  subtotal_amount: string;
  discount_amount: string;
  tax_amount: string;
  total_paid: string;
  currency_symbol: string;
  pickup_instructions: string[];
  is_reprint: boolean;
  reprint_count: number;
  reprint_label?: string | null;
}
