import { mobileApi } from "./client";

export const authApi = {
  login: async (payload: { identifier: string; password: string; device_info?: string }) =>
    (await mobileApi.post("/auth/login", payload)).data,

  register: async (payload: {
    full_name: string;
    email?: string | null;
    phone?: string | null;
    password: string;
    college_id_number?: string | null;
    department?: string | null;
    dietary_preference?: string | null;
    referral_code?: string | null;
  }) => (await mobileApi.post("/auth/register", payload)).data,

  requestOtp: async (payload: {
    target: string;
    purpose: "register" | "guest_checkout" | "login" | "phone_verify" | "email_verify" | "password_reset";
  }) => (await mobileApi.post("/auth/otp/request", payload)).data,

  verifyOtp: async (payload: {
    target: string;
    purpose: "register" | "guest_checkout" | "login" | "phone_verify" | "email_verify" | "password_reset";
    code: string;
  }) => (await mobileApi.post("/auth/otp/verify", payload)).data,

  otpLogin: async (payload: { target: string; code: string; device_info?: string }) =>
    (await mobileApi.post("/auth/otp/login", payload)).data,

  confirmPasswordReset: async (payload: { target: string; code: string; new_password: string }) =>
    (await mobileApi.post("/auth/password-reset/confirm", payload)).data,

  changePassword: async (payload: { current_password: string; new_password: string }) =>
    (await mobileApi.post("/auth/change-password", payload)).data,

  verifyPhone: async (payload: { target?: string; code: string }) =>
    (await mobileApi.post("/auth/phone/verify", payload)).data,

  me: async () => (await mobileApi.get("/auth/me")).data,

  logout: async () => (await mobileApi.post("/auth/logout")).data,
};
