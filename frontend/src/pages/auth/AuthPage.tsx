import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldCheck, Sparkles, UtensilsCrossed } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { Badge, Button, Card, Input, useToast } from "../../components/ui/Primitives";

const DEMO_USERS = import.meta.env.DEV
  ? [
      { label: "Student (Customer)", id: "student@collegebites.edu", pw: "Student@12345", dest: "/" },
      { label: "Kitchen Staff", id: "kitchen@collegebites.edu", pw: "Staff@12345", dest: "/kitchen" },
      { label: "Cashier POS", id: "cashier@collegebites.edu", pw: "Staff@12345", dest: "/cashier" },
      { label: "Pickup Scanner", id: "pickup@collegebites.edu", pw: "Staff@12345", dest: "/pickup" },
      { label: "Inventory Manager", id: "inventory@collegebites.edu", pw: "Staff@12345", dest: "/inventory" },
      { label: "Canteen Manager", id: "manager@collegebites.edu", pw: "Staff@12345", dest: "/admin" },
      { label: "College Admin", id: "admin@collegebites.edu", pw: "Admin@12345", dest: "/admin" },
    ]
  : [];

export const AuthPage: React.FC<{ initialMode?: "login" | "register" }> = ({ initialMode = "login" }) => {
  const [mode, setMode] = useState<"login" | "register">(initialMode);
  const [loginMethod, setLoginMethod] = useState<"password" | "otp">("password");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otpStatusMsg, setOtpStatusMsg] = useState<string | null>(null);
  const [devOtpHint, setDevOtpHint] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [collegeId, setCollegeId] = useState("");
  const [department, setDepartment] = useState("");
  const [referralCode, setReferralCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState("");
  const [resetCode, setResetCode] = useState("");
  const [resetNewPw, setResetNewPw] = useState("");
  const [resetSent, setResetSent] = useState(false);

  const navigate = useNavigate();
  const { setAuth } = useAppStore();
  const { pushToast } = useToast();

  const routeAfterAuth = (roles: string[], redirectPath?: string) => {
    if (redirectPath) return navigate(redirectPath);
    if (roles.includes("kitchen_staff")) navigate("/kitchen");
    else if (roles.includes("cashier")) navigate("/cashier");
    else if (roles.includes("pickup_staff")) navigate("/pickup");
    else if (roles.includes("inventory_manager")) navigate("/inventory");
    else if (roles.some((r) => ["super_admin", "college_admin", "canteen_manager"].includes(r))) navigate("/admin");
    else navigate("/");
  };

  const doLogin = async (idVal: string, pwVal: string, redirectPath?: string) => {
    setLoading(true);
    try {
      const res = await api.post("/auth/login", { identifier: idVal.trim(), password: pwVal.trim() });
      setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
      pushToast(`Welcome back, ${res.data.user.full_name}!`, "success");
      routeAfterAuth(res.data.user.roles || [], redirectPath);
    } catch (err) {
      pushToast(getApiError(err, "Login failed"), "error");
    } finally {
      setLoading(false);
    }
  };

  const requestLoginOtp = async () => {
    if (!identifier.trim()) return pushToast("Enter your email or mobile number first", "error");
    setLoading(true);
    setOtpStatusMsg(null);
    try {
      const res = await api.post("/auth/otp/request", { target: identifier.trim(), purpose: "login" });
      setOtpSent(true);
      setDevOtpHint(res.data.dev_otp || null);
      setOtpStatusMsg(res.data.message || "Login OTP sent!");
      pushToast(res.data.message || "Login OTP sent!", "success");
    } catch (err) {
      const msg = getApiError(err, "Could not request OTP");
      setOtpStatusMsg(msg);
      pushToast(msg, "error");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "login") {
      if (loginMethod === "otp") {
        setLoading(true);
        try {
          const res = await api.post("/auth/otp/login", { target: identifier.trim(), code: otpCode.trim() });
          setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
          pushToast(`Welcome back, ${res.data.user.full_name}!`, "success");
          routeAfterAuth(res.data.user.roles || []);
        } catch (err) {
          pushToast(getApiError(err, "OTP login failed"), "error");
        } finally {
          setLoading(false);
        }
        return;
      }
      await doLogin(identifier, password);
      return;
    }
    setLoading(true);
    try {
      const res = await api.post("/auth/register", {
        full_name: fullName,
        email: email || null,
        phone: phone || null,
        password,
        college_id_number: collegeId || null,
        department: department || null,
        referral_code: referralCode.trim() || null,
      });
      setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
      pushToast("Account created! Happy ordering.", "success");
      navigate("/");
    } catch (err) {
      pushToast(getApiError(err, "Registration failed"), "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <div className={import.meta.env.DEV ? "grid gap-6 md:grid-cols-2" : "mx-auto max-w-lg"}>
        <Card className="p-6 md:p-8">
          <div className="flex items-center gap-3 mb-6">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-orange-600 text-white">
              <UtensilsCrossed className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-extrabold text-slate-900">
                {mode === "login" ? "Sign in to CollegeBites" : "Create Universal Account"}
              </h1>
              <p className="text-xs text-slate-500">One account for students, faculty, visitors & staff</p>
            </div>
          </div>

          <div className="mb-5 flex rounded-xl bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`flex-1 rounded-lg py-2 text-sm font-bold ${mode === "login" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`flex-1 rounded-lg py-2 text-sm font-bold ${mode === "register" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}
            >
              Register
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "register" && (
              <>
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Full Name *</label>
                  <Input required value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Aarav Sharma" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block text-xs font-bold text-slate-700">Email</label>
                    <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@college.edu" />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-bold text-slate-700">Mobile Number</label>
                    <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+919876543210" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block text-xs font-bold text-slate-700">Roll / ID (Optional)</label>
                    <Input value={collegeId} onChange={(e) => setCollegeId(e.target.value)} placeholder="25AG1A6767" />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-bold text-slate-700">Department (Optional)</label>
                    <Input value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="CSE" />
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Referral Code (Optional)</label>
                  <Input value={referralCode} onChange={(e) => setReferralCode(e.target.value)} placeholder="Friend's referral code" />
                </div>
              </>
            )}

            {mode === "login" && (
              <>
                <div className="flex gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => setLoginMethod("password")}
                    className={`rounded-lg px-3 py-1 font-bold ${loginMethod === "password" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}
                  >
                    Password
                  </button>
                  <button
                    type="button"
                    onClick={() => setLoginMethod("otp")}
                    className={`rounded-lg px-3 py-1 font-bold ${loginMethod === "otp" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}
                  >
                    Mobile / Email OTP
                  </button>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Email or Mobile Number</label>
                  <Input
                    required
                    value={identifier}
                    onChange={(e) => setIdentifier(e.target.value)}
                    placeholder="you@college.edu"
                  />
                </div>
              </>
            )}

            {(mode === "register" || loginMethod === "password") ? (
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="text-xs font-bold text-slate-700">Password</label>
                  {mode === "login" && (
                    <button
                      type="button"
                      onClick={() => {
                        setResetTarget(identifier);
                        setResetSent(false);
                        setDevOtpHint(null);
                        setResetOpen(true);
                      }}
                      className="text-xs font-bold text-orange-600 hover:underline"
                    >
                      Forgot Password?
                    </button>
                  )}
                </div>
                <Input
                  type="password"
                  required
                  minLength={mode === "register" ? 8 : 1}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                />
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <Input
                    required
                    maxLength={6}
                    value={otpCode}
                    onChange={(e) => setOtpCode(e.target.value)}
                    placeholder="Enter 6-digit OTP"
                  />
                  <Button type="button" variant="outline" onClick={requestLoginOtp} disabled={loading}>
                    {otpSent ? "Resend" : "Send OTP"}
                  </Button>
                </div>
                {otpStatusMsg && (
                  <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-1.5 text-xs text-amber-900">
                    {otpStatusMsg}
                  </div>
                )}
                {devOtpHint && (
                  <div className="rounded-lg bg-slate-100 px-3 py-1.5 text-xs text-slate-700">
                    Dev/Test OTP: <strong className="font-mono">{devOtpHint}</strong>
                  </div>
                )}
                <p className="text-[11px] text-slate-500">
                  Email OTP delivers directly via SMTP. Requesting with a registered phone falls back to your linked account email unless SMS gateway is enabled.
                </p>
              </div>
            )}

            <Button type="submit" variant="primary" className="w-full" disabled={loading}>
              {loading ? "Please wait..." : mode === "login" ? (loginMethod === "otp" ? "Verify & Sign In" : "Sign In") : "Create Account"}
            </Button>
          </form>

          {resetOpen && (
            <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 space-y-2.5 text-xs">
              <div className="flex items-center justify-between font-bold text-slate-900">
                <span>Reset Password via OTP</span>
                <button type="button" onClick={() => setResetOpen(false)} className="text-slate-400 hover:text-slate-700">
                  Close
                </button>
              </div>
              <div className="flex gap-2">
                <Input value={resetTarget} onChange={(e) => setResetTarget(e.target.value)} placeholder="Registered Email or Mobile" />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={loading || !resetTarget.trim()}
                  onClick={async () => {
                    setLoading(true);
                    try {
                      const r = await api.post("/auth/otp/request", { target: resetTarget.trim(), purpose: "password_reset" });
                      setResetSent(true);
                      setDevOtpHint(r.data.dev_otp || null);
                      pushToast("Reset OTP sent!", "success");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    } finally {
                      setLoading(false);
                    }
                  }}
                >
                  {resetSent ? "Resend" : "Send OTP"}
                </Button>
              </div>
              {devOtpHint && (
                <div className="rounded-lg bg-white px-2.5 py-1 border border-slate-200">
                  Dev OTP: <strong className="font-mono">{devOtpHint}</strong>
                </div>
              )}
              <div className="grid grid-cols-2 gap-2">
                <Input value={resetCode} onChange={(e) => setResetCode(e.target.value)} placeholder="6-digit OTP" maxLength={6} />
                <Input type="password" value={resetNewPw} onChange={(e) => setResetNewPw(e.target.value)} placeholder="New password (8+ chars)" />
              </div>
              <Button
                type="button"
                size="sm"
                className="w-full"
                disabled={loading || resetCode.trim().length < 6 || resetNewPw.length < 8}
                onClick={async () => {
                  setLoading(true);
                  try {
                    await api.post("/auth/password-reset/confirm", {
                      target: resetTarget.trim(),
                      code: resetCode.trim(),
                      new_password: resetNewPw,
                    });
                    pushToast("Password updated! Sign in with your new password.", "success");
                    setResetOpen(false);
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  } finally {
                    setLoading(false);
                  }
                }}
              >
                Confirm New Password
              </Button>
            </div>
          )}

          <div className="mt-5 rounded-xl bg-orange-50 p-3 text-xs text-orange-900">
            <strong>Visiting campus?</strong> You can also skip login and order directly as a <strong>Guest</strong> at checkout with quick email or mobile OTP verification.
          </div>
        </Card>

        {import.meta.env.DEV && (
          <Card className="p-6 md:p-8 bg-slate-900 text-white border-slate-800">
            <div className="flex items-center gap-2 mb-3">
              <ShieldCheck className="h-5 w-5 text-orange-400" />
              <h2 className="text-lg font-extrabold">Role Workspaces (Seeded Dev Accounts)</h2>
            </div>
            <p className="text-xs text-slate-400 mb-5">
              One-click sign-in for local testing across customer, kitchen, cashier POS, pickup verification, inventory & administration roles.
            </p>
            <div className="space-y-2.5">
              {DEMO_USERS.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  disabled={loading}
                  onClick={() => doLogin(d.id, d.pw, d.dest)}
                  className="flex w-full items-center justify-between rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2.5 text-left transition hover:border-orange-500 hover:bg-slate-800"
                >
                  <div>
                    <div className="text-sm font-bold text-white">{d.label}</div>
                    <div className="text-[11px] text-slate-400">{d.id}</div>
                  </div>
                  <Badge tone="default" className="bg-orange-500/20 text-orange-300 border-orange-500/40">
                    <Sparkles className="h-3 w-3" /> Launch
                  </Badge>
                </button>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
};
