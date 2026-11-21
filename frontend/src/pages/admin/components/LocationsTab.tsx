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

  const { data: holidays = [], refetch: refetchHolidays } = useQuery<any[]>({
    queryKey: ["admin-holidays", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/admin/holidays?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: stations = [], refetch: refetchStations } = useQuery<any[]>({
    queryKey: ["admin-kitchen-stations", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/admin/canteens/${activeCanteenId}/kitchen-stations`)).data,
  });

  const { data: pickupLocs = [], refetch: refetchPickupLocs } = useQuery<any[]>({
    queryKey: ["admin-pickup-locs", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/admin/canteens/${activeCanteenId}/pickup-locations`)).data,
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
  const [stationKitchenId, setStationKitchenId] = useState("");
  const [stationName, setStationName] = useState("");
  const [pickupCounterId, setPickupCounterId] = useState("");
  const [pickupName, setPickupName] = useState("");
  const [pickupCode, setPickupCode] = useState("");
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
                    try {
                      await api.patch(`/admin/canteens/${c.id}`, { is_active: !c.is_active });
                      refetchCanteens();
                      pushToast(`Canteen ${!c.is_active ? "activated" : "deactivated"}`, "info");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  {c.is_active ? "Deactivate" : "Activate"}
                </Button>
                <Button
                  size="sm"
                  variant={c.is_temporarily_closed ? "danger" : "outline"}
                  onClick={async () => {
                    try {
                      await api.patch(`/admin/canteens/${c.id}`, { is_temporarily_closed: !c.is_temporarily_closed });
                      refetchCanteens();
                      pushToast(`Canteen ${!c.is_temporarily_closed ? "temporarily closed" : "reopened"}`, "info");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
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
            <div className="space-y-1.5 text-xs text-slate-600 max-h-36 overflow-y-auto">
              {detail.counters?.map((cnt: any) => (
                <div key={cnt.id} className="flex items-center justify-between gap-2">
                  <span>
                    • <strong>{cnt.name}</strong> ({cnt.code})
                  </span>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await api.patch(`/admin/counters/${cnt.id}`, { is_active: !cnt.is_active });
                        refetchDetail();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                    className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${cnt.is_active ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}
                  >
                    {cnt.is_active ? "Active" : "Paused"}
                  </button>
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

            <div className="border-t border-slate-100 pt-2 space-y-2">
              <div className="text-[11px] font-bold text-slate-700">Pickup Locations ({pickupLocs.length})</div>
              <div className="space-y-1 text-[11px] text-slate-600 max-h-20 overflow-y-auto">
                {pickupLocs.map((pl) => (
                  <div key={pl.id}>• {pl.name} ({pl.display_code})</div>
                ))}
              </div>
              <Select value={pickupCounterId} onChange={(e) => setPickupCounterId(e.target.value)}>
                <option value="">Select Counter</option>
                {detail.counters?.map((cnt: any) => (
                  <option key={cnt.id} value={cnt.id}>
                    {cnt.name}
                  </option>
                ))}
              </Select>
              <div className="grid grid-cols-2 gap-2">
                <Input value={pickupName} onChange={(e) => setPickupName(e.target.value)} placeholder="Parcel Shelf A" />
                <Input value={pickupCode} onChange={(e) => setPickupCode(e.target.value)} placeholder="PK-A" />
              </div>
              <Button
                size="sm"
                variant="outline"
                className="w-full"
                onClick={async () => {
                  try {
                    const cid = pickupCounterId || detail.counters?.[0]?.id;
                    if (!cid) return pushToast("Create a counter first", "error");
                    await api.post(`/admin/canteens/${activeCanteenId}/pickup-locations`, {
                      counter_id: cid,
                      name: pickupName,
                      display_code: pickupCode,
                    });
                    setPickupName("");
                    setPickupCode("");
                    refetchPickupLocs();
                    pushToast("Pickup location added", "success");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Add Pickup Location
              </Button>
            </div>
          </Card>

          <Card className="p-4 space-y-3">
            <h3 className="font-bold text-sm text-slate-900">Kitchens, Stations & Tables</h3>
            <div className="space-y-1 text-xs text-slate-600 max-h-24 overflow-y-auto">
              {detail.kitchens?.map((k: any) => (
                <div key={k.id} className="flex items-center justify-between">
                  <span>• {k.name} ({k.code})</span>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await api.patch(`/admin/kitchens/${k.id}`, { is_active: !k.is_active });
                        refetchDetail();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                    className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${k.is_active ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}
                  >
                    {k.is_active ? "Active" : "Paused"}
                  </button>
                </div>
              ))}
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

            <div className="border-t border-slate-100 pt-2 space-y-2">
              <div className="text-[11px] font-bold text-slate-700">Kitchen Stations ({stations.length})</div>
              <div className="flex flex-wrap gap-1">
                {stations.map((s) => (
                  <Badge key={s.id} tone="slate">{s.name}</Badge>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Select value={stationKitchenId} onChange={(e) => setStationKitchenId(e.target.value)}>
                  <option value="">Select Kitchen</option>
                  {detail.kitchens?.map((k: any) => (
                    <option key={k.id} value={k.id}>
                      {k.name}
                    </option>
                  ))}
                </Select>
                <Input value={stationName} onChange={(e) => setStationName(e.target.value)} placeholder="Tandoor / Grill" />
              </div>
              <Button
                size="sm"
                variant="outline"
                className="w-full"
                onClick={async () => {
                  try {
                    const kid = stationKitchenId || detail.kitchens?.[0]?.id;
                    if (!kid) return pushToast("Create a kitchen first", "error");
                    await api.post(`/admin/kitchens/${kid}/stations`, { name: stationName, station_type: "general" });
                    setStationName("");
                    refetchStations();
                    pushToast("Station added", "success");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Add Station
              </Button>
            </div>

            <div className="border-t border-slate-100 pt-2 space-y-2">
              <div className="text-[11px] font-bold text-slate-700">Dining Tables ({detail.tables?.length || 0})</div>
              <div className="flex flex-wrap gap-1">
                {detail.tables?.map((t: any) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={async () => {
                      try {
                        await api.patch(`/admin/tables/${t.id}`, { is_active: !t.is_active });
                        refetchDetail();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                    className={`rounded-full px-2 py-0.5 text-[10px] font-bold border ${t.is_active ? "bg-white border-slate-200 text-slate-700" : "bg-red-50 border-red-200 text-red-700"}`}
                  >
                    {t.table_number}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Input value={tableNo} onChange={(e) => setTableNo(e.target.value)} placeholder="T-03" />
                <Input value={zone} onChange={(e) => setZone(e.target.value)} placeholder="Zone" />
              </div>
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
                try {
                  await api.put(`/admin/canteens/${activeCanteenId}/hours`, [
                    { day_of_week: dayOfWeek, open_time: `${openTime}:00`, close_time: `${closeTime}:00`, is_closed: false },
                  ]);
                  refetchDetail();
                  refetchCanteens();
                  pushToast("Operating hour updated", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
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
                  refetchHolidays();
                  refetchCanteens();
                  pushToast("Holiday scheduled", "info");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Holiday Closure
            </Button>
            <div className="space-y-1 max-h-32 overflow-y-auto text-xs border-t border-slate-100 pt-2">
              {holidays.filter((h) => h.is_active).map((h) => (
                <div key={h.id} className="flex items-center justify-between gap-2">
                  <span>{h.holiday_date} • <strong>{h.title}</strong></span>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await api.delete(`/admin/holidays/${h.id}`);
                        refetchHolidays();
                        refetchCanteens();
                        pushToast("Holiday removed", "info");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                    className="text-red-600 font-bold hover:underline"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
};
