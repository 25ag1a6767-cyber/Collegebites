import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ShieldCheck, Sparkles } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, useToast } from "../../components/ui/Primitives";

const DEMO_USERS = import.meta.env.DEV
  ? [
      { label: "Student (Customer)", id: "student@collegebites.edu", pw: "Student@12345", dest: "/" },
      { label: "Kitchen Staff", id: "kitchen@collegebites.edu", pw: "Staff@12345", dest: "/kitchen" },
      { label: "Cashier POS", id: "cashier@collegebites.edu", pw: "Staff@12345", dest: "/cashier" },
      { label: "Pickup Scanner", id: "pickup@collegebites.edu", pw: "Staff@12345", dest: "/pickup" },
      { label: "Inventory Manager", id: "inventory@collegebites.edu", pw: "Staff@12345", dest: "/inventory" },
      { label: "Canteen Manager", id: "manager@collegebites.edu", pw: "Staff@12345", dest: "/command-center" },
      { label: "College Admin", id: "admin@collegebites.edu", pw: "Admin@12345", dest: "/command-center" },
    ]
  : [];

export const AuthPage: React.FC<{ initialMode?: "login" | "register" | "reset" }> = ({ initialMode = "login" }) => {
  const [searchParams] = useSearchParams();
  const urlToken = searchParams.get("token") || "";
  const [mode, setMode] = useState<"login" | "register">(initialMode === "register" ? "register" : "login");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [collegeId, setCollegeId] = useState("");
  const [department, setDepartment] = useState("");
  const [referralCode, setReferralCode] = useState("");
  const [loading, setLoading] = useState(false);

  // Secure non-OTP password recovery state (signed email reset link / token)
  const [resetOpen, setResetOpen] = useState(initialMode === "reset" || Boolean(urlToken));
  const [resetIdentifier, setResetIdentifier] = useState("");
  const [resetToken, setResetToken] = useState(urlToken);
  const [resetNewPw, setResetNewPw] = useState("");
  const [resetInfoMsg, setResetInfoMsg] = useState<string | null>(null);

  useEffect(() => {
    if (urlToken) {
      setResetToken(urlToken);
      setResetOpen(true);
    }
  }, [urlToken]);

  const navigate = useNavigate();
  const { setAuth } = useAppStore();
  const { pushToast } = useToast();

  const routeAfterAuth = (roles: string[], redirectPath?: string) => {
    if (redirectPath) return navigate(redirectPath);
    if (roles.includes("kitchen_staff")) navigate("/kitchen");
    else if (roles.includes("cashier")) navigate("/cashier");
    else if (roles.includes("pickup_staff")) navigate("/pickup");
    else if (roles.includes("inventory_manager")) navigate("/inventory");
    else if (roles.some((r) => ["super_admin", "college_admin", "canteen_manager"].includes(r))) navigate("/command-center");
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "login") {
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
            <BrandLogo size="md" />
            <div>
              <h1 className="text-xl font-extrabold text-slate-900">
                {mode === "login" ? "Sign in to CollegeBites" : "Create Universal Account"}
              </h1>
              <p className="text-xs text-slate-500">Secure password authentication for students, faculty & staff</p>
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
                  <label htmlFor="auth-fullname" className="mb-1 block text-xs font-bold text-slate-700">Full Name *</label>
                  <Input id="auth-fullname" required value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Aarav Sharma" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="auth-email" className="mb-1 block text-xs font-bold text-slate-700">Email</label>
                    <Input id="auth-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@college.edu" />
                  </div>
                  <div>
                    <label htmlFor="auth-phone" className="mb-1 block text-xs font-bold text-slate-700">Mobile Number</label>
                    <Input id="auth-phone" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+919876543210" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="auth-roll" className="mb-1 block text-xs font-bold text-slate-700">Roll / ID (Optional)</label>
                    <Input id="auth-roll" value={collegeId} onChange={(e) => setCollegeId(e.target.value)} placeholder="25AG1A6767" />
                  </div>
                  <div>
                    <label htmlFor="auth-dept" className="mb-1 block text-xs font-bold text-slate-700">Department (Optional)</label>
                    <Input id="auth-dept" value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="CSE" />
                  </div>
                </div>
                <div>
                  <label htmlFor="auth-ref" className="mb-1 block text-xs font-bold text-slate-700">Referral Code (Optional)</label>
                  <Input id="auth-ref" value={referralCode} onChange={(e) => setReferralCode(e.target.value)} placeholder="Friend's referral code" />
                </div>
              </>
            )}

            {mode === "login" && (
              <div>
                <label htmlFor="auth-identifier" className="mb-1 block text-xs font-bold text-slate-700">Email or Mobile Number</label>
                <Input
                  id="auth-identifier"
                  required
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder="you@college.edu"
                />
              </div>
            )}

            <div>
              <div className="mb-1 flex items-center justify-between">
                <label htmlFor="auth-password" className="text-xs font-bold text-slate-700">Password</label>
                {mode === "login" && (
                  <button
                    type="button"
                    onClick={() => {
                      setResetIdentifier(identifier);
                      setResetInfoMsg(null);
                      setResetOpen((v) => !v);
                    }}
                    className="text-xs font-bold text-[#76010d] hover:underline"
                  >
                    Forgot Password?
                  </button>
                )}
              </div>
              <Input
                id="auth-password"
                type="password"
                required
                minLength={mode === "register" ? 8 : 1}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </div>

            <Button type="submit" variant="primary" className="w-full" disabled={loading}>
              {loading ? "Please wait..." : mode === "login" ? "Sign In" : "Create Account"}
            </Button>
          </form>

          {resetOpen && (
            <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 space-y-2.5 text-xs">
              <div className="flex items-center justify-between font-bold text-slate-900">
                <span>Password Recovery (Secure Reset Link)</span>
                <button type="button" onClick={() => setResetOpen(false)} className="text-slate-400 hover:text-slate-700">
                  Close
                </button>
              </div>
              <div className="flex gap-2">
                <Input
                  aria-label="Account email or mobile for password reset"
                  value={resetIdentifier}
                  onChange={(e) => setResetIdentifier(e.target.value)}
                  placeholder="Registered email or mobile"
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={loading || resetIdentifier.trim().length < 3}
                  onClick={async () => {
                    setLoading(true);
                    try {
                      const res = await api.post("/auth/password-reset/request", { identifier: resetIdentifier.trim() });
                      setResetInfoMsg(res.data.message);
                      pushToast("Password reset request processed.", "info");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    } finally {
                      setLoading(false);
                    }
                  }}
                >
                  Send Link
                </Button>
              </div>
              {resetInfoMsg && <div className="rounded-lg bg-white border border-slate-200 p-2 text-[11px] text-slate-700">{resetInfoMsg}</div>}
              <Input
                aria-label="Password reset token"
                value={resetToken}
                onChange={(e) => setResetToken(e.target.value)}
                placeholder="Paste reset token from email link"
              />
              <Input
                aria-label="New password"
                type="password"
                value={resetNewPw}
                onChange={(e) => setResetNewPw(e.target.value)}
                placeholder="New password (8+ chars)"
              />
              <Button
                type="button"
                size="sm"
                className="w-full"
                disabled={loading || resetToken.trim().length < 16 || resetNewPw.length < 8}
                onClick={async () => {
                  setLoading(true);
                  try {
                    await api.post("/auth/password-reset/confirm", {
                      token: resetToken.trim(),
                      new_password: resetNewPw,
                    });
                    pushToast("Password updated! Sign in with your new password.", "success");
                    setResetOpen(false);
                    setResetToken("");
                    setResetNewPw("");
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

          <div className="mt-5 rounded-xl border border-[#76010d]/20 bg-[#fdf8f0] p-3 text-xs text-[#380106]">
            <strong>Visiting campus?</strong> You can skip login and order directly as a <strong>Guest</strong> at checkout with Razorpay payment and your signed QR pickup token.
          </div>
        </Card>

        {import.meta.env.DEV && (
          <Card className="p-6 md:p-8 bg-[#380106] text-white border-[#5d010a]">
            <div className="flex items-center gap-2 mb-3">
              <BrandLogo size="sm" variant="dark" />
              <ShieldCheck className="h-5 w-5 text-[#fdedce]" />
              <h2 className="text-lg font-extrabold">Role Workspaces (Seeded Dev Accounts)</h2>
            </div>
            <p className="text-xs text-[#fdedce]/80 mb-5">
              One-click sign-in for local testing across customer, kitchen, cashier POS, pickup verification, inventory & Command Center roles.
            </p>
            <div className="space-y-2.5">
              {DEMO_USERS.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  disabled={loading}
                  onClick={() => doLogin(d.id, d.pw, d.dest)}
                  className="flex w-full items-center justify-between rounded-xl border border-white/15 bg-white/5 px-4 py-2.5 text-left transition hover:border-[#fdedce]/60 hover:bg-white/10"
                >
                  <div>
                    <div className="text-sm font-bold text-white">{d.label}</div>
                    <div className="text-[11px] text-[#fdedce]/75">{d.id}</div>
                  </div>
                  <Badge tone="default" className="bg-[#76010d] text-[#fdedce] border-[#fdedce]/30">
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
