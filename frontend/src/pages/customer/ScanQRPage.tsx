import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Camera, CameraOff, CheckCircle2, QrCode, XCircle } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { Button, Card, Input } from "../../components/ui/Primitives";

function extractQrLocationCode(rawValue: string): string {
  const trimmed = rawValue.trim();
  const scanMarker = "/scan/";
  const idx = trimmed.indexOf(scanMarker);
  if (idx >= 0) {
    return trimmed.slice(idx + scanMarker.length).split(/[?#]/)[0].trim();
  }
  return trimmed;
}

export const ScanQRPage: React.FC = () => {
  const { code } = useParams<{ code?: string }>();
  const navigate = useNavigate();
  const { setSelectedCanteen } = useAppStore();
  const [error, setError] = useState<string | null>(null);
  const [resolved, setResolved] = useState<any>(null);
  const [manualCode, setManualCode] = useState("");
  const [resolving, setResolving] = useState(false);

  const [cameraActive, setCameraActive] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scanTimerRef = useRef<number | null>(null);

  const stopCamera = useCallback(() => {
    if (scanTimerRef.current !== null) {
      window.clearInterval(scanTimerRef.current);
      scanTimerRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setCameraActive(false);
  }, []);

  const resolveCode = useCallback(
    async (rawCode: string) => {
      const clean = extractQrLocationCode(rawCode);
      if (!clean) {
        setError("Enter a valid canteen, counter, or table QR code.");
        return;
      }
      setError(null);
      setResolving(true);
      try {
        const res = await api.get(`/qr/locations/resolve/${encodeURIComponent(clean)}`);
        setResolved(res.data);
        setSelectedCanteen(
          res.data.canteen.id,
          res.data.counter?.id || null,
          res.data.table?.id || null,
          res.data.qr.code
        );
        stopCamera();
      } catch (err) {
        setError(getApiError(err, "Invalid or revoked QR code"));
      } finally {
        setResolving(false);
      }
    },
    [setSelectedCanteen, stopCamera]
  );

  useEffect(() => {
    if (code) {
      void resolveCode(code);
    }
  }, [code, resolveCode]);

  useEffect(() => stopCamera, [stopCamera]);

  const startCamera = async () => {
    setCameraError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        setCameraError("Camera access is not available in this browser. Enter the QR code below.");
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      streamRef.current = stream;
      setCameraActive(true);
      window.setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
      }, 60);

      const BarcodeDetectorCtor = (window as unknown as { BarcodeDetector?: any }).BarcodeDetector;
      if (!BarcodeDetectorCtor) {
        setCameraError("Auto QR detection is unsupported on this browser — enter the code printed under the QR.");
        return;
      }
      const detector = new BarcodeDetectorCtor({ formats: ["qr_code"] });
      scanTimerRef.current = window.setInterval(async () => {
        if (!videoRef.current || videoRef.current.readyState < 2) return;
        try {
          const hits = await detector.detect(videoRef.current);
          if (hits?.length > 0 && hits[0].rawValue) {
            void resolveCode(String(hits[0].rawValue));
          }
        } catch {
          // keep scanning on transient frame errors
        }
      }, 500);
    } catch {
      setCameraError("Camera permission denied or unavailable. Enter the QR location code manually below.");
    }
  };

  if (!code && !resolved) {
    return (
      <div className="mx-auto max-w-lg px-4 py-8 space-y-4">
        <Card className="p-6 space-y-4">
          <div className="text-center space-y-1">
            <QrCode className="mx-auto h-10 w-10 text-orange-600" />
            <h1 className="text-xl font-extrabold text-slate-900">Scan Canteen / Table QR</h1>
            <p className="text-xs text-slate-500">
              Scan the QR sticker on your table, pickup counter, or canteen entrance to load the right menu instantly.
            </p>
          </div>

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
              {error}
            </div>
          )}

          {cameraActive ? (
            <div className="space-y-2">
              <div className="overflow-hidden rounded-2xl border-2 border-orange-500 bg-black aspect-[4/3]">
                <video ref={videoRef} playsInline muted className="h-full w-full object-cover" />
              </div>
              <Button variant="outline" className="w-full" onClick={stopCamera}>
                <CameraOff className="h-4 w-4" /> Stop Camera
              </Button>
            </div>
          ) : (
            <Button className="w-full" size="lg" onClick={startCamera}>
              <Camera className="h-4 w-4" /> Open Camera QR Scanner
            </Button>
          )}

          {cameraError && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {cameraError}
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void resolveCode(manualCode);
            }}
            className="space-y-2 pt-2 border-t border-slate-100"
          >
            <label className="text-xs font-bold text-slate-700">Or Enter QR Code Printed at Location</label>
            <div className="flex gap-2">
              <Input
                value={manualCode}
                onChange={(e) => setManualCode(e.target.value)}
                placeholder="e.g. CB-MAIN-T01"
                aria-label="Location QR code"
              />
              <Button type="submit" disabled={resolving || !manualCode.trim()}>
                {resolving ? "..." : "Open"}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-14">
      <Card className="p-8 text-center space-y-4">
        {error ? (
          <>
            <XCircle className="mx-auto h-12 w-12 text-red-600" />
            <h1 className="text-xl font-extrabold text-slate-900">QR Code Unavailable</h1>
            <p className="text-sm text-slate-600">{error}</p>
            <div className="flex flex-col sm:flex-row gap-2 justify-center">
              <Button onClick={() => { setError(null); setResolved(null); navigate("/scan"); }}>Scan Another QR</Button>
              <Button variant="outline" onClick={() => navigate("/")}>Browse Canteens</Button>
            </div>
          </>
        ) : resolved ? (
          <>
            <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" />
            <h1 className="text-xl font-extrabold text-slate-900">{resolved.canteen.name}</h1>
            <p className="text-sm text-slate-600">
              {resolved.table
                ? `Table ${resolved.table.table_number} (${resolved.table.zone_label || "Dine-in"})`
                : resolved.counter
                ? `Pickup Counter: ${resolved.counter.name}`
                : resolved.canteen.location}
            </p>
            <div className="rounded-xl bg-orange-50 p-3 text-xs text-orange-900">
              No login required — browse the menu and order as a guest or signed-in student.
            </div>
            <Button className="w-full" size="lg" onClick={() => navigate("/")}>
              Open Menu & Order Now
            </Button>
          </>
        ) : (
          <>
            <QrCode className="mx-auto h-12 w-12 animate-pulse text-orange-600" />
            <h1 className="text-lg font-bold text-slate-800">Identifying Canteen QR Location...</h1>
          </>
        )}
      </Card>
    </div>
  );
};
