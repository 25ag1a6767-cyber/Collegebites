import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { api } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen } from "../../types";
import { Select } from "../../components/ui/Primitives";
import { ForecastingAssistantTab } from "../admin/components/ForecastingAssistantTab";

export const AIAssistantPage: React.FC = () => {
  const { user, selectedCanteenId } = useAppStore();
  const isCollegeWide = Boolean(user?.roles?.some((r) => r === "super_admin" || r === "college_admin"));
  const canTrain = Boolean(user?.roles?.some((r) => ["super_admin", "college_admin", "canteen_manager"].includes(r)));

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState(user?.assigned_canteen_id || selectedCanteenId || "");
  useEffect(() => {
    if (!canteenId && canteens.length > 0) setCanteenId(canteens[0].id);
  }, [canteens, canteenId]);
  const activeId = (!isCollegeWide && user?.assigned_canteen_id) ? user.assigned_canteen_id : (canteenId || canteens[0]?.id || "");

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[#380106] p-4 text-white">
        <div className="flex items-center gap-3">
          <Bot className="h-6 w-6 text-[#fdedce]" />
          <div>
            <h1 className="text-xl font-extrabold">AI Forecasting &amp; Operations Assistant</h1>
            <p className="text-xs text-[#fdedce]/80">
              Role-scoped demand forecasting &amp; read-only operational intelligence
            </p>
          </div>
        </div>
        <Select
          value={activeId}
          disabled={!isCollegeWide && Boolean(user?.assigned_canteen_id)}
          onChange={(e) => setCanteenId(e.target.value)}
          className="w-56 bg-slate-800 border-slate-700 text-white"
        >
          {canteens.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      </div>
      <ForecastingAssistantTab activeCanteenId={activeId} canTrainForecast={canTrain} />
    </div>
  );
};
