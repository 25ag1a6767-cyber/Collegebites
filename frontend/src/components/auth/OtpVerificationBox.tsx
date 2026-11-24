import React, { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Clock, Loader2, Mail, RefreshCw } from "lucide-react";
import axios from "axios";
import { api, getApiError } from "../../api/client";
import { Button, Input } from "../ui/Primitives";

export type OtpPurpose =
  | "register"
  | "login"
  | "guest_checkout"
  | "password_reset"
  | "phone_verify"
  | "email_verify";

export interface OtpVerificationBoxProps {
  target: string;
  onTargetChange?: (next: string) => void;
  targetLabel?: string;
  targetPlaceholder?: string;
  purpose: OtpPurpose;
  verifiedToken?: string | null;
  isVerified?: boolean;
  onVerified?: (verificationToken: string) => void;
  customVerifyRequest?: (code: string) => Promise<void>;
  verifyButtonLabel?: string;
  hideVerifyButton?: boolean;
  codeValue?: string;
  onCodeChange?: (code: string) => void;
  compact?: boolean;
}

function parseRetrySeconds(err: unknown, fallback = 60): number | null {
  if (!axios.isAxiosError(err)) return null;
  if (err.response?.status !== 429) return null;
  const headerVal = err.response.headers?.["retry-after"];
  if (headerVal && !Number.isNaN(Number(headerVal))) {
    return Math.max(1, Number(headerVal));
  }
  const detail = String(err.response?.data?.detail || "");
  const m = detail.match(/(\d+)\s*s/i);
  if (m) return Math.max(1, Number(m[1]));
  return fallback;
}

function formatSecs(total: number): string {
  const s = Math.max(0, Math.floor(total));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

export const OtpVerificationBox: React.FC<OtpVerificationBoxProps> = ({
  target,
  onTargetChange,
  targetLabel,
  targetPlaceholder = "you@college.edu",
  purpose,
  verifiedToken,
  isVerified = false,
  onVerified,
  customVerifyRequest,
  verifyButtonLabel = "Verify OTP",
  hideVerifyButton = false,
  codeValue,
  onCodeChange,
  compact = false,
}) => {
  const [internalCode, setInternalCode] = useState("");
  const code = codeValue !== undefined ? codeValue : internalCode;
  const setCode = (next: string) => {
    const digitsOnly = next.replace(/\D/g, "").slice(0, 6);
    if (onCodeChange) onCodeChange(digitsOnly);
    else setInternalCode(digitsOnly);
  };

  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [otpSent, setOtpSent] = useState(false);
  const [cooldownLeft, setCooldownLeft] = useState(0);
  const [expiryLeft, setExpiryLeft] = useState(0);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [localVerified, setLocalVerified] = useState(false);

  const verified = Boolean(isVerified || verifiedToken || localVerified);

  useEffect(() => {
    if (cooldownLeft <= 0 && expiryLeft <= 0) return;
    const id = setInterval(() => {
      setCooldownLeft((c) => (c > 0 ? c - 1 : 0));
      setExpiryLeft((e) => {
        if (e === 1) {
          setErrorMessage("Verification code has expired. Please tap Resend OTP for a fresh code.");
        }
        return e > 0 ? e - 1 : 0;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [cooldownLeft, expiryLeft]);

  const handleSendOtp = async () => {
    const cleanTarget = target.trim();
    setErrorMessage(null);
    setInfoMessage(null);
    if (!cleanTarget) {
      setErrorMessage("Please enter a valid email address or mobile number first.");
      return;
    }
    setSending(true);
    try {
      const res = await api.post("/auth/otp/request", {
        target: cleanTarget,
        purpose,
      });
      const data = res.data || {};
      setOtpSent(true);
      setLocalVerified(false);
      setCode("");
      setCooldownLeft(Number(data.resend_cooldown_seconds ?? 60));
      setExpiryLeft(Number(data.expires_in_seconds ?? 300));
      setInfoMessage(data.message || "Verification code sent! Check your inbox.");
    } catch (err) {
      const retrySecs = parseRetrySeconds(err);
      if (retrySecs && retrySecs <= 120) {
        setCooldownLeft(retrySecs);
      }
      setErrorMessage(getApiError(err, "Could not deliver verification code. Please try again."));
    } finally {
      setSending(false);
    }
  };

  const handleVerifyOtp = async () => {
    const cleanTarget = target.trim();
    const cleanCode = code.trim();
    setErrorMessage(null);
    if (!cleanTarget) {
      setErrorMessage("Please enter your email or mobile number.");
      return;
    }
    if (cleanCode.length !== 6) {
      setErrorMessage("Enter the complete 6-digit verification code.");
      return;
    }
    setVerifying(true);
    try {
      if (customVerifyRequest) {
        await customVerifyRequest(cleanCode);
        setLocalVerified(true);
        setInfoMessage("Verification complete!");
      } else {
        const res = await api.post("/auth/otp/verify", {
          target: cleanTarget,
          purpose,
          code: cleanCode,
        });
        setLocalVerified(true);
        setInfoMessage("Verified successfully!");
        onVerified?.(res.data.verification_token);
      }
    } catch (err) {
      setErrorMessage(getApiError(err, "Invalid or expired OTP code."));
    } finally {
      setVerifying(false);
    }
  };

  if (verified) {
    return (
      <div className="inline-flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-800">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
        <span>OTP Verified ({target.trim()})</span>
      </div>
    );
  }

  return (
    <div className={`space-y-2.5 ${compact ? "" : "rounded-xl border border-slate-200 bg-slate-50/70 p-3.5"}`}>
      {onTargetChange ? (
        <div>
          {targetLabel && <label className="mb-1 block text-xs font-bold text-slate-700">{targetLabel}</label>}
          <div className="flex flex-wrap gap-2">
            <Input
              value={target}
              onChange={(e) => onTargetChange(e.target.value)}
              placeholder={targetPlaceholder}
              className="flex-1 min-w-[200px]"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={sending || cooldownLeft > 0 || !target.trim()}
              onClick={handleSendOtp}
            >
              {sending ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Sending...
                </>
              ) : cooldownLeft > 0 ? (
                <>
                  <Clock className="h-3.5 w-3.5" /> Resend in {cooldownLeft}s
                </>
              ) : otpSent ? (
                <>
                  <RefreshCw className="h-3.5 w-3.5" /> Resend OTP
                </>
              ) : (
                <>
                  <Mail className="h-3.5 w-3.5" /> Send OTP
                </>
              )}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs text-slate-600">
            Destination: <strong className="text-slate-900">{target.trim() || "Enter above"}</strong>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={sending || cooldownLeft > 0 || !target.trim()}
            onClick={handleSendOtp}
          >
            {sending ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Sending...
              </>
            ) : cooldownLeft > 0 ? (
              <>
                <Clock className="h-3.5 w-3.5" /> Resend in {cooldownLeft}s
              </>
            ) : otpSent ? (
              <>
                <RefreshCw className="h-3.5 w-3.5" /> Resend OTP
              </>
            ) : (
              <>
                <Mail className="h-3.5 w-3.5" /> Send OTP
              </>
            )}
          </Button>
        </div>
      )}

      {infoMessage && !errorMessage && (
        <div className="flex items-center justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-900">
          <span>{infoMessage}</span>
          {expiryLeft > 0 && <span className="font-mono font-semibold">Expires {formatSecs(expiryLeft)}</span>}
        </div>
      )}

      {errorMessage && (
        <div className="flex items-start gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-800">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-600 mt-0.5" />
          <span>{errorMessage}</span>
        </div>
      )}

      {otpSent && (
        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="6-digit OTP"
            className="w-36 font-mono tracking-widest text-center"
          />
          {!hideVerifyButton && (
            <Button
              type="button"
              size="sm"
              variant="primary"
              disabled={verifying || code.trim().length !== 6 || expiryLeft === 0}
              onClick={handleVerifyOtp}
            >
              {verifying ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Verifying...
                </>
              ) : (
                verifyButtonLabel
              )}
            </Button>
          )}
        </div>
      )}
    </div>
  );
};
