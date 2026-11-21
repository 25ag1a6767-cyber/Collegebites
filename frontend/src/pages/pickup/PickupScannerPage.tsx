import React, { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Html5Qrcode } from "html5-qrcode";
import { AlertTriangle, Camera, CheckCircle2, QrCode, ShieldAlert, XCircle } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen } from "../../types";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";

export const PickupScannerPage: React.FC = () => {
  const { pushToast } = useToast();
  const { user, selectedCanteenId } = useAppStore();

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState(user?.assigned_canteen_id || selectedCanteenId || "");
  const activeCanteenId = canteenId || canteens[0]?.id || "";
  const { data: canteenDetail } = useQuery<Canteen>({
    queryKey: ["canteen-detail", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/canteens/${activeCanteenId}`)).data,
  });

  const [counterId, setCounterId] = useState("");
  const [manualInput, setManualInput] = useState("");
  const [verifyMode, setVerifyMode] = useState<"qr" | "token" | "order">("token");
  const [result, setResult] = useState<any>(null);
  const [cameraActive, setCameraActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const scannerRef = useRef<Html5Qrcode | null>(null);

  const runVerification = async (payload: { qr_payload?: string; pickup_token?: string; order_number?: string }) => {
    setBusy(true);
    try {
      const res = await api.post("/pickup/verify", {
        ...payload,
        canteen_id: activeCanteenId || null,
        counter_id: counterId || null,
      });
      setResult(res.data);
    } catch (err) {
      pushToast(getApiError(err, "Verification error"), "error");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const hash = window.location.hash || "";
    const qs = new URLSearchParams(window.location.search);
    const hashMatch = hash.match(/token=([^&]+)/);
    const rawTok = (hashMatch ? decodeURIComponent(hashMatch[1]) : "") || qs.get("token") || "";
    if (rawTok) {
      setVerifyMode("qr");
      setManualInput(rawTok);
      void runVerification({ qr_payload: rawTok });
    }
  }, []);

  const startCamera = () => {
    setCameraActive(true);
    setTimeout(async () => {
      try {
        const html5Qr = new Html5Qrcode("cb-qr-reader");
        scannerRef.current = html5Qr;
        await html5Qr.start(
          { facingMode: "environment" },
          { fps: 10, qrbox: { width: 240, height: 240 } },
          async (decodedText) => {
            try {
              await html5Qr.stop();
            } catch {
              // ignore stop race
            }
            setCameraActive(false);
            void runVerification({ qr_payload: decodedText });
          },
          () => {}
        );
      } catch {
        setCameraActive(false);
        pushToast("Camera unavailable; use manual QR/Token lookup.", "error");
      }
    }, 100);
  };

  const stopCamera = async () => {
    try {
      await scannerRef.current?.stop();
    } catch {
      // ignore
    }
    setCameraActive(false);
  };

  useEffect(() => {
    return () => {
      scannerRef.current?.stop().catch(() => {});
    };
  }, []);

  const handleManualSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualInput.trim()) return;
    if (verifyMode === "qr") runVerification({ qr_payload: manualInput.trim() });
    else if (verifyMode === "token") runVerification({ pickup_token: manualInput.trim() });
    else runVerification({ order_number: manualInput.trim() });
  };

  const confirmHandover = async () => {
    if (!result?.order_id) return;
    setBusy(true);
    try {
      await api.post("/pickup/handover", {
        order_id: result.order_id,
        counter_id: counterId || result.counter_id || null,
        verification_method: verifyMode === "qr" ? "qr_scan" : verifyMode === "token" ? "manual_token" : "order_number",
      });
      pushToast(`Handover confirmed for Token ${result.pickup_token}!`, "success");
      setResult({ ...result, can_handover: false, order_status: "COMPLETED", result_code: "COMPLETED", message: "Food handed over and order marked COMPLETED." });
    } catch (err) {
      pushToast(getApiError(err, "Handover failed"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-900 p-4 text-white">
        <div className="flex items-center gap-3">
          <QrCode className="h-7 w-7 text-emerald-400" />
          <div>
            <h1 className="text-xl font-extrabold">QR Pickup Verification & Handover</h1>
            <p className="text-xs text-slate-400">
              Scanning verifies authenticity separately — staff must explicitly confirm food handover.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Select
            value={activeCanteenId}
            onChange={(e) => {
              setCanteenId(e.target.value);
              setCounterId("");
            }}
            className="w-44 bg-slate-800 border-slate-700 text-white"
          >
            {canteens.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Select
            value={counterId}
            onChange={(e) => setCounterId(e.target.value)}
            className="w-44 bg-slate-800 border-slate-700 text-white"
          >
            <option value="">Any Counter</option>
            {canteenDetail?.counters?.map((cnt) => (
              <option key={cnt.id} value={cnt.id}>
                {cnt.name}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-slate-900">1. Scan QR or Enter Token</h2>
            {!cameraActive ? (
              <Button size="sm" variant="primary" onClick={startCamera}>
                <Camera className="h-4 w-4" /> Open Camera Scanner
              </Button>
            ) : (
              <Button size="sm" variant="danger" onClick={stopCamera}>
                Stop Camera
              </Button>
            )}
          </div>

          {cameraActive && <div id="cb-qr-reader" className="overflow-hidden rounded-xl border border-slate-300" />}

          <form onSubmit={handleManualSubmit} className="space-y-3 border-t border-slate-100 pt-3">
            <div className="flex gap-1.5">
              {[
                { k: "token", l: "Pickup Token" },
                { k: "qr", l: "QR Payload" },
                { k: "order", l: "Order Number" },
              ].map((m) => (
                <button
                  key={m.k}
                  type="button"
                  onClick={() => setVerifyMode(m.k as any)}
                  className={`flex-1 rounded-lg py-1.5 text-xs font-bold ${
                    verifyMode === m.k ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {m.l}
                </button>
              ))}
            </div>
            <Input
              value={manualInput}
              onChange={(e) => setManualInput(e.target.value)}
              placeholder={
                verifyMode === "token"
                  ? "e.g. A001"
                  : verifyMode === "order"
                  ? "e.g. CB-20261121-000001"
                  : "Paste QR URL or CBQR...."
              }
            />
            <Button type="submit" className="w-full">
              Verify Order
            </Button>
          </form>
        </Card>

        <Card className="p-5 space-y-4">
          <h2 className="font-bold text-slate-900">2. Verification & Handover</h2>
          {!result ? (
            <div className="py-12 text-center text-xs text-slate-400">
              Scan customer QR code or enter pickup token to inspect items & payment status.
            </div>
          ) : (
            <div className="space-y-4">
              <div
                className={`flex items-start gap-3 rounded-xl border p-3.5 text-sm ${
                  result.can_handover || result.result_code === "COMPLETED"
                    ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                    : result.result_code === "ORDER_NOT_READY" || result.result_code === "WRONG_COUNTER"
                    ? "border-amber-300 bg-amber-50 text-amber-950"
                    : "border-red-300 bg-red-50 text-red-900"
                }`}
              >
                {result.can_handover || result.result_code === "COMPLETED" ? (
                  <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
                ) : result.result_code === "ORDER_NOT_READY" || result.result_code === "WRONG_COUNTER" ? (
                  <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" />
                ) : (
                  <XCircle className="h-5 w-5 shrink-0 text-red-600" />
                )}
                <div>
                  <div className="font-extrabold">{result.result_code}</div>
                  <div className="text-xs mt-0.5">{result.message}</div>
                  {result.previous_handover_at && (
                    <div className="text-xs font-bold mt-1">
                      Collected previously at: {new Date(result.previous_handover_at).toLocaleString()}
                    </div>
                  )}
                </div>
              </div>

              {result.order_number && (
                <div className="space-y-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Order / Token:</span>
                    <span className="font-extrabold text-slate-900">
                      {result.order_number} / {result.pickup_token}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Assigned Counter:</span>
                    <span className="font-bold text-slate-900">{result.counter_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Payment / Status:</span>
                    <span className="flex gap-1.5">
                      <Badge tone="green">{result.payment_status}</Badge>
                      <Badge tone="blue">{result.order_status}</Badge>
                    </span>
                  </div>

                  {result.items?.length > 0 && (
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-1.5">
                      <div className="font-bold uppercase text-[10px] text-slate-500">Items to Hand Over</div>
                      {result.items.map((it: any, i: number) => (
                        <div key={i} className="font-semibold text-slate-900">
                          {it.quantity}× {it.item_name} {it.variant_name ? `(${it.variant_name})` : ""}
                          {it.customizations?.length > 0 && (
                            <div className="pl-3 font-normal text-slate-600">{it.customizations.join(", ")}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {result.can_handover && (
                <Button variant="success" size="lg" className="w-full" disabled={busy} onClick={confirmHandover}>
                  <ShieldAlert className="h-4 w-4" /> Confirm Food Handover (Mark COMPLETED)
                </Button>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};
