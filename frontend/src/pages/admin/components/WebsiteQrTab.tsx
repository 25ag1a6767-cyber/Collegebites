import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Download, ExternalLink, Printer, QrCode, ShieldAlert } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import type { Canteen, FoodCategory } from "../../../types";
import { BrandLogo, COLLEGEBITES_LOGO_SRC } from "../../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../../components/ui/Primitives";

interface GeneratedWebsiteQR {
  target_type: "website" | "canteen" | "menu";
  target_url: string;
  title: string;
  subtitle: string;
  college_name: string;
  college_logo_url?: string | null;
  canteen_name?: string | null;
  category_name?: string | null;
  poster_headline: string;
  filename_base: string;
  png_base64: string;
  svg_markup: string;
}

export const WebsiteQrTab: React.FC<{
  canteens: Canteen[];
  defaultCanteenId: string;
  downloadBlob: (url: string, filename: string) => Promise<void>;
}> = ({ canteens, defaultCanteenId, downloadBlob }) => {
  const { pushToast } = useToast();

  const { data: config } = useQuery<any>({
    queryKey: ["website-qr-config"],
    queryFn: async () => (await api.get("/qr/website/config")).data,
  });

  const [targetType, setTargetType] = useState<"website" | "canteen" | "menu">("website");
  const [selectedCanteenId, setSelectedCanteenId] = useState(defaultCanteenId || canteens[0]?.id || "");
  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [includeLogo, setIncludeLogo] = useState(true);
  const [customLogoUrl, setCustomLogoUrl] = useState("");
  const [posterHeadline, setPosterHeadline] = useState("Scan to Order Food");
  const [generated, setGenerated] = useState<GeneratedWebsiteQR | null>(null);
  const [posterModalOpen, setPosterModalOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!selectedCanteenId && canteens.length > 0) setSelectedCanteenId(canteens[0].id);
  }, [canteens, selectedCanteenId]);

  useEffect(() => {
    if (config?.college_logo_url && !customLogoUrl) {
      setCustomLogoUrl(config.college_logo_url);
    }
  }, [config]);

  const { data: categories = [] } = useQuery<FoodCategory[]>({
    queryKey: ["website-qr-cats", selectedCanteenId],
    enabled: Boolean(selectedCanteenId && targetType === "menu"),
    queryFn: async () => (await api.get(`/menus/canteens/${selectedCanteenId}/categories`)).data,
  });

  const generateQr = async () => {
    setBusy(true);
    try {
      const res = await api.post<GeneratedWebsiteQR>("/qr/website/generate", {
        target_type: targetType,
        canteen_id: targetType === "website" ? null : selectedCanteenId,
        category_id: targetType === "menu" && selectedCategoryId ? selectedCategoryId : null,
        box_size: 12,
      });
      setGenerated(res.data);
      pushToast("Website QR generated from configured public URL", "success");
    } catch (err) {
      pushToast(getApiError(err, "Failed to generate Website QR"), "error");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (config && config.is_valid_public_url && !generated) {
      void generateQr();
    }
  }, [config]);

  const activeLogoUrl = includeLogo ? (customLogoUrl.trim() || generated?.college_logo_url || COLLEGEBITES_LOGO_SRC) : "";
  const buildDownloadQuery = (fmt: "png" | "svg") => {
    const qs = new URLSearchParams({ format: fmt, target_type: generated?.target_type || targetType });
    if ((generated?.target_type || targetType) !== "website" && selectedCanteenId) qs.set("canteen_id", selectedCanteenId);
    if ((generated?.target_type || targetType) === "menu" && selectedCategoryId) qs.set("category_id", selectedCategoryId);
    return `/qr/website/download?${qs.toString()}`;
  };

  const printPoster = () => {
    setPosterModalOpen(true);
    setTimeout(() => {
      window.print();
    }, 180);
  };

  const PosterContent = () => {
    if (!generated) return null;
    return (
      <div className="cb-poster-print mx-auto max-w-md rounded-3xl border-2 border-slate-900 bg-white p-7 text-center shadow-lg space-y-4">
        {/* Branding Header */}
        <div className="flex flex-col items-center gap-2">
          {activeLogoUrl ? (
            <img
              src={activeLogoUrl}
              alt={generated.college_name}
              className="h-14 w-14 rounded-2xl object-contain border border-[#76010d]/20 p-0.5 bg-[#fdf8f0]"
            />
          ) : (
            <BrandLogo size="lg" />
          )}
          <div className="text-xs font-extrabold uppercase tracking-widest text-[#76010d]">
            CollegeBites Official Ordering Portal
          </div>
          <div className="text-xl font-black text-slate-900">{generated.college_name}</div>
          <Badge tone="slate">{generated.subtitle}</Badge>
        </div>

        {/* High-Contrast QR Code SVG/PNG */}
        <div className="mx-auto inline-block rounded-2xl border-2 border-slate-200 bg-white p-4">
          <img
            src={`data:image/png;base64,${generated.png_base64}`}
            alt={`QR Code for ${generated.target_url}`}
            className="mx-auto h-56 w-56 object-contain"
          />
        </div>

        {/* Call to Action */}
        <div className="space-y-1">
          <div className="text-2xl font-black tracking-tight text-slate-900">
            {posterHeadline.trim() || "Scan to Order Food"}
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            Point your phone camera at this QR code to open the live digital canteen menu, customize meals, pay online or at the counter, and receive an instant pickup token.
          </p>
        </div>

        {/* Actual Verified Public URL */}
        <div className="rounded-xl bg-slate-100 px-3 py-2 font-mono text-[11px] text-slate-800 break-all">
          {generated.target_url}
        </div>
      </div>
    );
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Configuration Card */}
      <Card className="p-5 space-y-4 no-print">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <QrCode className="h-4 w-4 text-[#76010d]" /> Website QR Code Generator
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Separate from table/location &amp; order pickup QRs. Always uses the environment public frontend URL.
            </p>
          </div>
          {config && (
            <Badge tone={config.is_valid_public_url ? "green" : "red"}>
              {config.is_production ? "Production" : "Dev Env"}
            </Badge>
          )}
        </div>

        {/* Environment URL Status */}
        <div
          className={`rounded-xl border p-3 text-xs ${
            config?.is_valid_public_url
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-red-200 bg-red-50 text-red-900"
          }`}
        >
          <div className="font-bold flex items-center gap-1.5">
            {!config?.is_valid_public_url && <ShieldAlert className="h-4 w-4" />}
            Configured Public Frontend URL:
          </div>
          <div className="font-mono mt-1 break-all">{config?.public_frontend_url || "Loading..."}</div>
        </div>

        {/* Target Scope Selector */}
        <div className="space-y-2 text-xs">
          <label className="font-bold text-slate-700 block">QR Destination Type</label>
          <div className="grid grid-cols-3 gap-2">
            {(
              [
                { k: "website", l: "Full Website" },
                { k: "canteen", l: "Specific Canteen" },
                { k: "menu", l: "Menu / Category" },
              ] as const
            ).map((opt) => (
              <button
                key={opt.k}
                type="button"
                onClick={() => {
                  setTargetType(opt.k);
                  setSelectedCategoryId("");
                }}
                className={`rounded-xl border py-2 px-2 font-bold ${
                  targetType === opt.k ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-white text-slate-700"
                }`}
              >
                {opt.l}
              </button>
            ))}
          </div>
        </div>

        {targetType !== "website" && (
          <div className="grid gap-3 sm:grid-cols-2 text-xs">
            <div>
              <label className="font-bold text-slate-700 block mb-1">Canteen</label>
              <Select
                value={selectedCanteenId}
                onChange={(e) => {
                  setSelectedCanteenId(e.target.value);
                  setSelectedCategoryId("");
                }}
              >
                {canteens.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} (/{c.slug})
                  </option>
                ))}
              </Select>
            </div>
            {targetType === "menu" && (
              <div>
                <label className="font-bold text-slate-700 block mb-1">Food Category (Optional)</label>
                <Select value={selectedCategoryId} onChange={(e) => setSelectedCategoryId(e.target.value)}>
                  <option value="">All Categories (#menu)</option>
                  {categories.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
          </div>
        )}

        {/* Poster Branding Options */}
        <div className="space-y-2.5 border-t border-slate-100 pt-3 text-xs">
          <div className="font-bold text-slate-700">Poster Branding &amp; Logo</div>
          <Input
            value={posterHeadline}
            onChange={(e) => setPosterHeadline(e.target.value)}
            placeholder="Scan to Order Food"
          />
          <label className="flex items-center gap-2 font-semibold text-slate-700 cursor-pointer">
            <input type="checkbox" checked={includeLogo} onChange={(e) => setIncludeLogo(e.target.checked)} />
            Include Optional College Logo on Poster
          </label>
          {includeLogo && (
            <Input
              value={customLogoUrl}
              onChange={(e) => setCustomLogoUrl(e.target.value)}
              placeholder="College Logo URL (https://... optional, defaults to College Settings)"
            />
          )}
        </div>

        <Button onClick={generateQr} disabled={busy} className="w-full">
          <QrCode className="h-4 w-4" /> {busy ? "Generating..." : "Generate Website QR Preview"}
        </Button>

        {generated && (
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => downloadBlob(buildDownloadQuery("png"), `${generated.filename_base}.png`)}
              >
                <Download className="h-3.5 w-3.5" /> Download PNG
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => downloadBlob(buildDownloadQuery("svg"), `${generated.filename_base}.svg`)}
              >
                <Download className="h-3.5 w-3.5" /> Download SVG
              </Button>
              <Button size="sm" variant="secondary" onClick={printPoster}>
                <Printer className="h-3.5 w-3.5" /> Print Poster
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  navigator.clipboard?.writeText(generated.target_url);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1800);
                }}
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />} Copy URL
              </Button>
              <a href={generated.target_url} target="_blank" rel="noopener noreferrer">
                <Button size="sm" variant="ghost">
                  <ExternalLink className="h-3.5 w-3.5" /> Open URL
                </Button>
              </a>
            </div>
          </div>
        )}
      </Card>

      {/* Poster Preview */}
      <div className="space-y-3">
        <div className="flex items-center justify-between no-print">
          <h3 className="font-bold text-slate-900 text-sm">Printable Poster Preview</h3>
          {generated && (
            <Button size="sm" variant="outline" onClick={() => setPosterModalOpen(true)}>
              Full-Screen Poster View
            </Button>
          )}
        </div>
        {generated ? (
          <PosterContent />
        ) : (
          <Card className="p-10 text-center text-xs text-slate-500">
            Click &ldquo;Generate Website QR Preview&rdquo; to build a downloadable PNG/SVG and printable poster.
          </Card>
        )}
      </div>

      {/* Printable Poster Modal */}
      <Modal
        open={posterModalOpen}
        onClose={() => setPosterModalOpen(false)}
        title="Printable Website Ordering Poster"
        maxWidth="max-w-lg"
      >
        <div className="space-y-4">
          <PosterContent />
          <div className="flex justify-center gap-2 no-print">
            <Button size="sm" onClick={() => window.print()}>
              <Printer className="h-3.5 w-3.5" /> Print Now
            </Button>
            {generated && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => downloadBlob(buildDownloadQuery("png"), `${generated.filename_base}.png`)}
                >
                  Download PNG
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => downloadBlob(buildDownloadQuery("svg"), `${generated.filename_base}.svg`)}
                >
                  Download SVG
                </Button>
              </>
            )}
          </div>
        </div>
      </Modal>
    </div>
  );
};
