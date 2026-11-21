import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, getApiError } from "../../../api/client";
import type { Canteen } from "../../../types";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

interface Props {
  canteens: Canteen[];
  activeCanteenId: string;
  refetchCanteens: () => void;
}

export const LocationsTab: React.FC<Props> = ({ canteens, activeCanteenId, refetchCanteens }) => {
  const { pushToast } = useToast();
  const { data: detail, refetch: refetchDetail } = useQuery<any>({
    queryKey: ["admin-canteen-detail", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/canteens/${activeCanteenId}`)).data,
  });

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [code, setCode] = useState("");
  const [loc, setLoc] = useState("");
  const [counterName, setCounterName] = useState("");
  const [counterCode, setCounterCode] = useState("");
  const [kitchenName, setKitchenName] = useState("");
  const [kitchenCode, setKitchenCode] = useState("");
  const [tableNo, setTableNo] = useState("");
  const [zone, setZone] = useState("Main Hall");
  const [holDate, setHolDate] = useState("");
  const [holTitle, setHolTitle] = useState("");
  const [openTime, setOpenTime] = useState("07:30");
  const [closeTime, setCloseTime] = useState("21:30");
  const [dayOfWeek, setDayOfWeek] = useState(0);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900">Campus Canteens & Locations</h2>
          {canteens.map((c) => (
            <div key={c.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-3 text-xs">
              <div>
                <div className="font-bold text-sm">
                  {c.name} ({c.code})
                </div>
                <div className="text-slate-500">
                  {c.location} • Prefix: {c.token_prefix}
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant={c.is_active ? "outline" : "success"}
                  onClick={async () => {
                    await api.patch(`/admin/canteens/${c.id}`, { is_active: !c.is_active });
                    refetchCanteens();
                  }}
                >
                  {c.is_active ? "Deactivate" : "Activate"}
                </Button>
                <Button
                  size="sm"
                  variant={c.is_temporarily_closed ? "danger" : "outline"}
                  onClick={async () => {
                    await api.patch(`/admin/canteens/${c.id}`, { is_temporarily_closed: !c.is_temporarily_closed });
                    refetchCanteens();
                  }}
                >
                  {c.is_temporarily_closed ? "Reopen" : "Temp Close"}
                </Button>
              </div>
            </div>
          ))}
        </Card>

        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900">Create New Campus Canteen / Counter Location</h2>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (e.g. MBA Block Cafe)" />
          <div className="grid grid-cols-2 gap-2">
            <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="slug (mba-cafe)" />
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="code (MBA)" />
          </div>
          <Input value={loc} onChange={(e) => setLoc(e.target.value)} placeholder="Building / Floor" />
          <Button
            onClick={async () => {
              try {
                await api.post("/admin/canteens", {
                  name,
                  slug,
                  code,
                  location: loc,
                  token_prefix: code.slice(0, 1).toUpperCase() || "M",
                });
                setName("");
                setSlug("");
                setCode("");
                setLoc("");
                pushToast("Canteen created!", "success");
                refetchCanteens();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Add Canteen Location
          </Button>
        </Card>
      </div>

      {detail && (
        <div className="grid gap-5 md:grid-cols-3">
          <Card className="p-4 space-y-3">
            <h3 className="font-bold text-sm text-slate-900">Counters ({detail.counters?.length || 0})</h3>
            <div className="space-y-1 text-xs text-slate-600 max-h-28 overflow-y-auto">
              {detail.counters?.map((cnt: any) => (
                <div key={cnt.id}>
                  • <strong>{cnt.name}</strong> ({cnt.code})
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input value={counterName} onChange={(e) => setCounterName(e.target.value)} placeholder="Counter 3" />
              <Input value={counterCode} onChange={(e) => setCounterCode(e.target.value)} placeholder="C3" />
            </div>
            <Button
              size="sm"
              className="w-full"
              onClick={async () => {
                try {
                  await api.post(`/admin/canteens/${activeCanteenId}/counters`, {
                    name: counterName,
                    code: counterCode,
                    counter_type: "both",
                  });
                  setCounterName("");
                  setCounterCode("");
                  refetchDetail();
                  pushToast("Counter added", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Counter
            </Button>
          </Card>

          <Card className="p-4 space-y-3">
            <h3 className="font-bold text-sm text-slate-900">Kitchens & Tables</h3>
            <div className="text-xs text-slate-600">
              Kitchens: {detail.kitchens?.map((k: any) => k.name).join(", ") || "None"}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input value={kitchenName} onChange={(e) => setKitchenName(e.target.value)} placeholder="Bakery Kitchen" />
              <Input value={kitchenCode} onChange={(e) => setKitchenCode(e.target.value)} placeholder="K2" />
            </div>
            <Button
              size="sm"
              variant="outline"
              className="w-full"
              onClick={async () => {
                try {
                  await api.post(`/admin/canteens/${activeCanteenId}/kitchens`, {
                    name: kitchenName,
                    code: kitchenCode,
                  });
                  setKitchenName("");
                  setKitchenCode("");
                  refetchDetail();
                  pushToast("Kitchen added", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Kitchen
            </Button>
            <div className="border-t border-slate-100 pt-2 grid grid-cols-2 gap-2">
              <Input value={tableNo} onChange={(e) => setTableNo(e.target.value)} placeholder="T-03" />
              <Input value={zone} onChange={(e) => setZone(e.target.value)} placeholder="Zone" />
            </div>
            <Button
              size="sm"
              className="w-full"
              onClick={async () => {
                try {
                  await api.post(`/admin/canteens/${activeCanteenId}/tables`, {
                    table_number: tableNo,
                    zone_label: zone,
                  });
                  setTableNo("");
                  refetchDetail();
                  pushToast("Table added", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Dining Table
            </Button>
          </Card>

          <Card className="p-4 space-y-3">
            <h3 className="font-bold text-sm text-slate-900">Operating Hours & Holidays</h3>
            <div className="grid grid-cols-3 gap-2">
              <Select value={dayOfWeek} onChange={(e) => setDayOfWeek(Number(e.target.value))}>
                {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, idx) => (
                  <option key={d} value={idx}>
                    {d}
                  </option>
                ))}
              </Select>
              <Input type="time" value={openTime} onChange={(e) => setOpenTime(e.target.value)} />
              <Input type="time" value={closeTime} onChange={(e) => setCloseTime(e.target.value)} />
            </div>
            <Button
              size="sm"
              variant="outline"
              className="w-full"
              onClick={async () => {
                await api.put(`/admin/canteens/${activeCanteenId}/hours`, [
                  { day_of_week: dayOfWeek, open_time: `${openTime}:00`, close_time: `${closeTime}:00`, is_closed: false },
                ]);
                refetchDetail();
                pushToast("Operating hour updated", "success");
              }}
            >
              Save Day Hours
            </Button>
            <div className="border-t border-slate-100 pt-2 grid grid-cols-2 gap-2">
              <Input type="date" value={holDate} onChange={(e) => setHolDate(e.target.value)} />
              <Input value={holTitle} onChange={(e) => setHolTitle(e.target.value)} placeholder="Holiday title" />
            </div>
            <Button
              size="sm"
              variant="danger"
              className="w-full"
              onClick={async () => {
                try {
                  await api.post("/admin/holidays", {
                    canteen_id: activeCanteenId,
                    holiday_date: holDate,
                    title: holTitle,
                    is_full_day: true,
                  });
                  setHolTitle("");
                  refetchDetail();
                  refetchCanteens();
                  pushToast("Holiday scheduled", "info");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Holiday Closure
            </Button>
          </Card>
        </div>
      )}
    </div>
  );
};
