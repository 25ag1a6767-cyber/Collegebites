import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  BrainCircuit,
  Clock,
  FileSearch,
  History,
  MessageSquarePlus,
  RefreshCw,
  Send,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Modal, useToast } from "../../../components/ui/Primitives";

interface Props {
  activeCanteenId: string;
  canTrainForecast?: boolean;
  canViewForecast?: boolean;
  canViewAudit?: boolean;
}

export const ForecastingAssistantTab: React.FC<Props> = ({
  activeCanteenId,
  canTrainForecast = true,
  canViewForecast = true,
  canViewAudit = false,
}) => {
  const { pushToast } = useToast();
  const [subTab, setSubTab] = useState<"forecast" | "assistant">(canViewForecast ? "forecast" : "assistant");
  const [training, setTraining] = useState(false);

  // Assistant states
  const [question, setQuestion] = useState("");
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [asking, setAsking] = useState(false);
  const [showAuditModal, setShowAuditModal] = useState(false);

  useEffect(() => {
    if (!canViewForecast && subTab === "forecast") {
      setSubTab("assistant");
    }
  }, [canViewForecast, subTab]);

  const {
    data: forecast,
    isLoading: forecastLoading,
    isError: forecastError,
    error: forecastErrObj,
    refetch: refetchForecast,
  } = useQuery<any>({
    queryKey: ["ai-forecast", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "forecast" && canViewForecast),
    queryFn: async () => (await api.get(`/forecasting/canteens/${activeCanteenId}`)).data,
  });

  const { data: models = [], refetch: refetchModels } = useQuery<any[]>({
    queryKey: ["ai-forecast-models", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "forecast" && canViewForecast),
    queryFn: async () => (await api.get(`/forecasting/canteens/${activeCanteenId}/models`)).data,
  });

  const { data: evaluations } = useQuery<any>({
    queryKey: ["ai-forecast-evals", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "forecast" && canViewForecast),
    queryFn: async () => (await api.get(`/forecasting/canteens/${activeCanteenId}/evaluations?lookback_days=30`)).data,
  });

  const { data: conversations = [], refetch: refetchConvs } = useQuery<any[]>({
    queryKey: ["ai-assistant-convs", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "assistant"),
    queryFn: async () => (await api.get("/ai-assistant/conversations")).data,
  });

  const { data: auditLogs = [] } = useQuery<any[]>({
    queryKey: ["ai-assistant-audit", activeCanteenId],
    enabled: Boolean(activeCanteenId && showAuditModal && canViewAudit),
    queryFn: async () => (await api.get(`/ai-assistant/audit-logs?canteen_id=${activeCanteenId}`)).data,
  });

  const handleLoadConversation = async (id: string) => {
    try {
      const res = await api.get(`/ai-assistant/conversations/${id}`);
      setConvId(res.data.id);
      setMessages(res.data.messages || []);
    } catch (err) {
      pushToast(getApiError(err, "Failed to load conversation"), "error");
    }
  };

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
      refetchConvs();
    } catch (err) {
      pushToast(getApiError(err, "Assistant request failed"), "error");
    } finally {
      setAsking(false);
    }
  };

  const comparisonEntries = Object.entries(forecast?.active_model?.comparison_metrics || {});

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {canViewForecast && (
          <Button size="sm" variant={subTab === "forecast" ? "secondary" : "outline"} onClick={() => setSubTab("forecast")}>
            <TrendingUp className="h-3.5 w-3.5" /> AI Demand Forecasting (ML)
          </Button>
        )}
        <Button size="sm" variant={subTab === "assistant" ? "secondary" : "outline"} onClick={() => setSubTab("assistant")}>
          <Bot className="h-3.5 w-3.5" /> AI Canteen Assistant (Read-Only)
        </Button>
      </div>

      {subTab === "forecast" && canViewForecast && (
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
                    refetchModels();
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

          {forecastLoading ? (
            <Card className="p-6 text-center text-xs text-slate-500">Loading ML demand forecasts...</Card>
          ) : forecastError ? (
            <Card className="p-4 border-red-200 bg-red-50 text-xs text-red-700">
              {getApiError(forecastErrObj, "Failed to load demand forecast data.")}
            </Card>
          ) : forecast?.status !== "ok" ? (
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

              {/* 7-Day Item Forecast Table */}
              {(forecast.seven_day_forecasts || []).length > 0 && (
                <Card className="p-4 space-y-2 overflow-x-auto">
                  <h3 className="font-bold text-slate-900 text-sm">7-Day Aggregated Item Forecasts (AI Predicted)</h3>
                  <table className="w-full text-xs text-left">
                    <thead className="border-b border-slate-200 text-slate-500 uppercase">
                      <tr>
                        <th className="py-1.5 pr-3">Menu Item</th>
                        <th className="py-1.5 pr-3">Category</th>
                        <th className="py-1.5 pr-3">7d Total Predicted</th>
                        <th className="py-1.5">Uncertainty Band</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {forecast.seven_day_forecasts.slice(0, 15).map((row: any) => (
                        <tr key={row.food_item_id}>
                          <td className="py-1.5 pr-3 font-bold text-slate-900">{row.food_item_name}</td>
                          <td className="py-1.5 pr-3 text-slate-600">{row.category_name}</td>
                          <td className="py-1.5 pr-3 font-mono font-bold text-[#76010d]">{row.total_predicted_quantity}</td>
                          <td className="py-1.5 font-mono text-slate-500">[{row.total_lower_bound} – {row.total_upper_bound}]</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}

              {/* Model Comparison + Peak Hours + Realized Evaluations */}
              <div className="grid gap-4 lg:grid-cols-2">
                {comparisonEntries.length > 0 && (
                  <Card className="p-4 space-y-2 overflow-x-auto">
                    <h3 className="font-bold text-slate-900 text-sm">Model Benchmark Comparison (Chronological Holdout)</h3>
                    <table className="w-full text-xs text-left">
                      <thead className="border-b border-slate-200 text-slate-500 uppercase">
                        <tr>
                          <th className="py-1.5 pr-3">Algorithm</th>
                          <th className="py-1.5 pr-3">MAE</th>
                          <th className="py-1.5 pr-3">RMSE</th>
                          <th className="py-1.5">MAPE %</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {comparisonEntries.map(([alg, m]: [string, any]) => (
                          <tr key={alg} className={alg === forecast.active_model?.algorithm ? "bg-emerald-50/50 font-bold" : ""}>
                            <td className="py-1.5 pr-3">
                              {alg} {alg === forecast.active_model?.algorithm && <Badge tone="green">Selected</Badge>}
                            </td>
                            <td className="py-1.5 pr-3 font-mono">{m.mae}</td>
                            <td className="py-1.5 pr-3 font-mono">{m.rmse}</td>
                            <td className="py-1.5 font-mono">{m.mape ?? "N/A"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {evaluations?.realized_vs_predicted && (
                      <div className="pt-2 border-t border-slate-100 text-[11px] text-slate-600">
                        <strong>Realized vs Predicted (30d):</strong>{" "}
                        {evaluations.realized_vs_predicted.status === "ok"
                          ? `${evaluations.realized_vs_predicted.evaluated_pairs} pairs — MAE ${evaluations.realized_vs_predicted.mae}, RMSE ${evaluations.realized_vs_predicted.rmse}`
                          : evaluations.realized_vs_predicted.message}
                      </div>
                    )}
                  </Card>
                )}

                <Card className="p-4 space-y-2">
                  <h3 className="font-bold text-slate-900 text-sm">Peak Ordering Hours (30d) &amp; Model History ({models.length})</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {(forecast.peak_ordering_periods || []).map((p: any) => (
                      <Badge key={p.hour} tone="amber">
                        <Clock className="h-3 w-3 inline mr-1" /> {p.hour} ({p.historical_orders_30d} orders)
                      </Badge>
                    ))}
                  </div>
                  {models.length > 0 && (
                    <div className="pt-2 border-t border-slate-100 space-y-1 max-h-40 overflow-y-auto text-[11px]">
                      {models.slice(0, 6).map((m: any) => (
                        <div key={m.id} className="flex items-center justify-between text-slate-600">
                          <span className="font-mono">{m.model_version} ({m.algorithm})</span>
                          <span>MAE {m.mae} {m.is_active ? "• ACTIVE" : ""}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </div>
            </div>
          )}
        </div>
      )}

      {subTab === "assistant" && (
        <div className="grid gap-4 lg:grid-cols-12">
          {/* Conversation History Sidebar */}
          <Card className="lg:col-span-3 p-3.5 space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                <History className="h-3.5 w-3.5 text-[#76010d]" /> Conversations
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setConvId(null);
                  setMessages([]);
                }}
              >
                <MessageSquarePlus className="h-3.5 w-3.5" /> New
              </Button>
            </div>
            <div className="space-y-1.5 max-h-[420px] overflow-y-auto">
              {conversations.length === 0 ? (
                <div className="text-[11px] text-slate-400 text-center py-4">No saved conversations yet.</div>
              ) : (
                conversations.map((c: any) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => void handleLoadConversation(c.id)}
                    className={`w-full text-left rounded-lg border px-2.5 py-2 text-xs transition ${
                      convId === c.id ? "border-[#76010d] bg-[#fdf8f0] font-bold" : "border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <div className="truncate text-slate-900">{c.title}</div>
                    <div className="text-[10px] text-slate-400">
                      {c.updated_at ? new Date(c.updated_at).toLocaleDateString() : ""}
                    </div>
                  </button>
                ))
              )}
            </div>
          </Card>

          <Card className="lg:col-span-9 p-4 space-y-4">
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
              {canViewAudit && (
                <Button size="sm" variant="outline" onClick={() => setShowAuditModal(true)}>
                  <FileSearch className="h-3.5 w-3.5" /> Audit Log
                </Button>
              )}
            </div>

            <div className="flex flex-wrap gap-1.5">
              {[
                "What are today's total sales and revenue?",
                "Which items sold the most today?",
                "Which ingredients are running low?",
                "What is the current queue wait time?",
                "How much food was wasted this week?",
                "What is the food safety compliance status?",
                ...(canViewForecast ? ["What is expected demand tomorrow?"] : []),
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
                        {(m.last_updated || m.created_at) && (
                          <span className="text-[10px] text-slate-400">
                            Updated: {new Date(m.last_updated || m.created_at).toLocaleTimeString()}
                          </span>
                        )}
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
        </div>
      )}

      {/* AI Assistant Audit Log Modal (Admin / Manager) */}
      <Modal open={showAuditModal} onClose={() => setShowAuditModal(false)} title="AI Assistant Governance & Query Audit Log">
        <div className="space-y-2 max-h-96 overflow-y-auto text-xs">
          {auditLogs.length === 0 ? (
            <div className="text-slate-500 text-center py-6">No assistant queries logged yet.</div>
          ) : (
            auditLogs.map((a: any) => (
              <div
                key={a.id}
                className={`rounded-lg border p-2.5 space-y-1 ${a.blocked_action_attempted ? "border-red-300 bg-red-50/40" : "border-slate-200"}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-slate-900">{a.question}</span>
                  <Badge tone={a.blocked_action_attempted ? "red" : "slate"}>{a.data_classification}</Badge>
                </div>
                <div className="text-[11px] text-slate-500">
                  Roles: {(a.user_roles || []).join(", ")} • Tools: {(a.tools_invoked || []).join(", ") || "none"} • {a.response_ms}ms
                </div>
                <div className="text-[10px] text-slate-400">{a.created_at ? new Date(a.created_at).toLocaleString() : ""}</div>
              </div>
            ))
          )}
        </div>
      </Modal>
    </div>
  );
};
