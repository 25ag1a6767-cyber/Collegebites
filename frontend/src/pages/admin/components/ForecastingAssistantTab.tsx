import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, BrainCircuit, RefreshCw, Send, ShieldAlert, TrendingUp } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, useToast } from "../../../components/ui/Primitives";

interface Props {
  activeCanteenId: string;
  canTrainForecast?: boolean;
}

export const ForecastingAssistantTab: React.FC<Props> = ({ activeCanteenId, canTrainForecast = true }) => {
  const { pushToast } = useToast();
  const [subTab, setSubTab] = useState<"forecast" | "assistant">("forecast");
  const [training, setTraining] = useState(false);

  // Assistant states
  const [question, setQuestion] = useState("");
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [asking, setAsking] = useState(false);

  const { data: forecast, refetch: refetchForecast } = useQuery<any>({
    queryKey: ["ai-forecast", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "forecast"),
    queryFn: async () => (await api.get(`/forecasting/canteens/${activeCanteenId}`)).data,
  });

  const handleAsk = async (qOverride?: string) => {
    const qText = (qOverride ?? question).trim();
    if (!qText || !activeCanteenId) return;
    setAsking(true);
    setMessages((prev) => [...prev, { role: "user", content: qText }]);
    setQuestion("");
    try {
      const res = await api.post("/ai-assistant/ask", {
        canteen_id: activeCanteenId,
        question: qText,
        conversation_id: convId,
      });
      setConvId(res.data.conversation_id);
      setMessages((prev) => [...prev, { role: "assistant", ...res.data }]);
    } catch (err) {
      pushToast(getApiError(err, "Assistant request failed"), "error");
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={subTab === "forecast" ? "secondary" : "outline"} onClick={() => setSubTab("forecast")}>
          <TrendingUp className="h-3.5 w-3.5" /> AI Demand Forecasting (ML)
        </Button>
        <Button size="sm" variant={subTab === "assistant" ? "secondary" : "outline"} onClick={() => setSubTab("assistant")}>
          <Bot className="h-3.5 w-3.5" /> AI Canteen Assistant (Read-Only)
        </Button>
      </div>

      {subTab === "forecast" && (
        <div className="space-y-4">
          <Card className="p-4 flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2 font-bold text-slate-900">
                <BrainCircuit className="h-4 w-4 text-[#76010d]" /> Demand Forecasting Pipeline
                <Badge tone="blue">AI PREDICTED</Badge>
              </div>
              <div className="text-xs text-slate-500">
                Trained strictly on verified historical paid orders with chronological validation (Baseline vs Ridge vs RandomForest vs GradientBoosting).
              </div>
            </div>
            {canTrainForecast && (
              <Button
                size="sm"
                variant="primary"
                disabled={training || !activeCanteenId}
                onClick={async () => {
                  setTraining(true);
                  try {
                    const res = await api.post("/forecasting/train", {
                      canteen_id: activeCanteenId,
                      training_window_days: 60,
                      horizon_days: 7,
                      force_retrain: true,
                    });
                    if (res.data.status === "insufficient_data") {
                      pushToast(res.data.message, "info");
                    } else {
                      pushToast(`Forecast model ${res.data.active_model?.model_version} trained successfully`, "success");
                    }
                    refetchForecast();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  } finally {
                    setTraining(false);
                  }
                }}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${training ? "animate-spin" : ""}`} /> Train / Refresh Forecast Model
              </Button>
            )}
          </Card>

          {forecast?.status !== "ok" ? (
            <Card className="p-6 border-amber-200 bg-amber-50 text-sm text-amber-900">
              {forecast?.message || "Insufficient historical data to generate a reliable forecast."}
            </Card>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Card className="p-3.5">
                  <div className="text-[11px] text-slate-500">Active ML Model</div>
                  <div className="font-extrabold text-sm text-slate-900">{forecast.active_model?.algorithm}</div>
                  <div className="text-[11px] font-mono text-slate-500">{forecast.active_model?.model_version}</div>
                </Card>
                <Card className="p-3.5">
                  <div className="text-[11px] text-slate-500">Validation MAE / RMSE</div>
                  <div className="text-lg font-black text-slate-900">
                    {forecast.active_model?.mae} / {forecast.active_model?.rmse}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    Baseline MAE: {forecast.active_model?.baseline_mae}
                  </div>
                </Card>
                <Card className="p-3.5">
                  <div className="text-[11px] text-slate-500">Historical Sales Days Used</div>
                  <div className="text-lg font-black text-slate-900">{forecast.active_model?.historical_days_used}</div>
                  <div className="text-[11px] text-slate-500">MAPE: {forecast.active_model?.mape ?? "N/A"}%</div>
                </Card>
                <Card className="p-3.5 border-amber-200 bg-amber-50/40">
                  <div className="text-[11px] text-amber-800">Potential 7d Ingredient Shortages</div>
                  <div className="text-lg font-black text-amber-900">{forecast.potential_shortages?.length ?? 0}</div>
                  <div className="text-[11px] text-amber-800">Based on verified recipes</div>
                </Card>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <Card className="p-4 space-y-2">
                  <h3 className="font-bold text-slate-900 text-sm">Next-Day Predicted Demand (AI Predicted)</h3>
                  {(forecast.next_day_forecasts || []).map((f: any) => (
                    <div key={f.food_item_id} className="rounded-xl border border-slate-200 p-2.5 text-xs flex items-center justify-between">
                      <div>
                        <div className="font-bold text-slate-900">{f.food_item_name}</div>
                        <div className="text-slate-500">{f.category_name} • {f.forecast_date}</div>
                      </div>
                      <div className="text-right">
                        <div className="font-black text-[#76010d]">{f.predicted_quantity} units</div>
                        <div className="text-[10px] text-slate-500">Band: [{f.lower_bound} – {f.upper_bound}]</div>
                      </div>
                    </div>
                  ))}
                </Card>

                <Card className="p-4 space-y-2">
                  <h3 className="font-bold text-slate-900 text-sm">Projected Recipe Ingredient Shortages (7d)</h3>
                  {(forecast.potential_shortages || []).length === 0 ? (
                    <div className="text-xs text-slate-500 py-4">No ingredient shortages projected for next 7 days.</div>
                  ) : (
                    forecast.potential_shortages.map((s: any) => (
                      <div key={s.inventory_item_id} className="rounded-xl border border-amber-200 bg-amber-50 p-2.5 text-xs flex items-center justify-between">
                        <div>
                          <div className="font-bold text-amber-900">{s.ingredient_name}</div>
                          <div className="text-amber-800">Usable: {s.usable_stock} {s.unit} • Needed: {s.forecasted_7d_requirement} {s.unit}</div>
                        </div>
                        <Badge tone="red">Deficit {s.projected_deficit}</Badge>
                      </div>
                    ))
                  )}
                </Card>
              </div>
            </div>
          )}
        </div>
      )}

      {subTab === "assistant" && (
        <Card className="p-4 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
            <div>
              <div className="font-bold text-slate-900 flex items-center gap-2">
                <Bot className="h-4 w-4 text-[#76010d]" /> Controlled Role-Aware AI Canteen Assistant
                <Badge tone="green">READ-ONLY</Badge>
              </div>
              <div className="text-xs text-slate-500">
                Grounded strictly in verified database services. Cannot approve POs, alter prices/inventory, or issue refunds.
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {[
              "What are today's total sales and revenue?",
              "Which items sold the most today?",
              "Which ingredients are running low?",
              "What is the current queue wait time?",
              "How much food was wasted this week?",
              "What is the food safety compliance status?",
              "What is expected demand tomorrow?",
            ].map((sample) => (
              <button
                key={sample}
                type="button"
                onClick={() => handleAsk(sample)}
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-100"
              >
                {sample}
              </button>
            ))}
          </div>

          <div className="space-y-3 max-h-96 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50/50 p-3">
            {messages.length === 0 ? (
              <div className="text-xs text-slate-400 text-center py-8">
                Ask any operational question about sales, top items, inventory, wastage, queue load, food safety, or demand forecasts.
              </div>
            ) : (
              messages.map((m, idx) => (
                <div
                  key={idx}
                  className={`rounded-xl p-3 text-xs space-y-1.5 ${
                    m.role === "user"
                      ? "bg-[#380106] text-white ml-8"
                      : m.blocked_action_attempted
                      ? "bg-red-50 border border-red-200 text-red-900 mr-8"
                      : "bg-white border border-slate-200 text-slate-800 mr-8"
                  }`}
                >
                  {m.role === "assistant" && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      {m.blocked_action_attempted && <ShieldAlert className="h-3.5 w-3.5 text-red-600" />}
                      <Badge
                        tone={
                          m.data_classification === "policy_restricted"
                            ? "red"
                            : m.data_classification === "ai_predicted"
                            ? "blue"
                            : m.data_classification === "estimated"
                            ? "amber"
                            : "green"
                        }
                      >
                        {(m.data_classification || "actual").toUpperCase()}
                      </Badge>
                      <span className="text-[10px] text-slate-500">Source: {m.data_source}</span>
                      <span className="text-[10px] text-slate-400">Range: {m.date_range}</span>
                    </div>
                  )}
                  <div className="whitespace-pre-line font-medium">{m.content || m.answer}</div>
                  {m.role === "assistant" && m.limitations && (
                    <div className="text-[10px] text-slate-500 border-t border-slate-100 pt-1">
                      Note: {m.limitations}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleAsk();
            }}
            className="flex gap-2"
          >
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about sales, low stock, queue wait, food safety, or forecasts..."
              className="flex-1"
            />
            <Button type="submit" variant="primary" disabled={asking || !question.trim()}>
              <Send className="h-4 w-4" /> Ask
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
};
