import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, QrCode, XCircle } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { Button, Card } from "../../components/ui/Primitives";

export const ScanQRPage: React.FC = () => {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const { setSelectedCanteen } = useAppStore();
  const [error, setError] = useState<string | null>(null);
  const [resolved, setResolved] = useState<any>(null);

  useEffect(() => {
    if (!code) return;
    api
      .get(`/qr/locations/resolve/${encodeURIComponent(code)}`)
      .then((res) => {
        setResolved(res.data);
        setSelectedCanteen(
          res.data.canteen.id,
          res.data.counter?.id || null,
          res.data.table?.id || null,
          res.data.qr.code
        );
      })
      .catch((err) => setError(getApiError(err, "Invalid or revoked QR code")));
  }, [code, setSelectedCanteen]);

  return (
    <div className="mx-auto max-w-lg px-4 py-14">
      <Card className="p-8 text-center space-y-4">
        {error ? (
          <>
            <XCircle className="mx-auto h-12 w-12 text-red-600" />
            <h1 className="text-xl font-extrabold text-slate-900">QR Code Unavailable</h1>
            <p className="text-sm text-slate-600">{error}</p>
            <Button onClick={() => navigate("/")}>Browse Available Canteens</Button>
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
