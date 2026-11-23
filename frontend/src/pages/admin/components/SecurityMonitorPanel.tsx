import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FileSearch, Lock, QrCode, ShieldAlert, Unlock } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

export const SecurityMonitorPanel: React.FC<{
  isCollegeAdmin: boolean;
  activeCanteenId: string;
}> = ({ isCollegeAdmin, activeCanteenId }) => {
  const { pushToast } = useToast();
  const [subTab, setSubTab] = useState<"alerts" | "qr" | "logins" | "audit">("alerts");
  const [alertStatus, setAlertStatus] = useState<string>("open");
  const [qrValidity, setQrValidity] = useState<string>("false");
  const [loginFilter, setLoginFilter] = useState<string>("");
  const [loginSuccessFilter, setLoginSuccessFilter] = useState<string>("false");
  const [auditSearch, setAuditSearch] = useState<string>("");
  const [auditIp, setAuditIp] = useState<string>("");
  const [auditAction, setAuditAction] = useState<string>("");

  const canteenQuery = !isCollegeAdmin && activeCanteenId ? `canteen_id=${activeCanteenId}` : "";

  const { data: dash, refetch: refetchDash } = useQuery<any>({
    queryKey: ["security-dashboard", activeCanteenId, isCollegeAdmin],
    queryFn: async () => (await api.get(`/security/dashboard${canteenQuery ? `?${canteenQuery}` : ""}`)).data,
  });

  const { data: alerts = [], refetch: refetchAlerts } = useQuery<any[]>({
    queryKey: ["security-alerts", activeCanteenId, isCollegeAdmin, alertStatus],
    queryFn: async () => {
      const p = new URLSearchParams();
      if (canteenQuery && activeCanteenId) p.set("canteen_id", activeCanteenId);
      if (alertStatus !== "all") p.set("status_filter", alertStatus);
      return (await api.get(`/security/alerts?${p.toString()}`)).data;
    },
  });

  const { data: qrEvents = [] } = useQuery<any[]>({
    queryKey: ["security-qr-events", activeCanteenId, isCollegeAdmin, qrValidity],
    enabled: subTab === "qr",
    queryFn: async () => {
      const p = new URLSearchParams();
      if (canteenQuery && activeCanteenId) p.set("canteen_id", activeCanteenId);
      if (qrValidity !== "all") p.set("is_valid", qrValidity);
      return (await api.get(`/security/qr-events?${p.toString()}`)).data;
    },
  });

  const { data: loginAttempts = [] } = useQuery<any[]>({
    queryKey: ["security-login-attempts", loginFilter, loginSuccessFilter],
    enabled: isCollegeAdmin && subTab === "logins",
    queryFn: async () => {
      const p = new URLSearchParams();
      if (loginFilter.trim()) p.set("identifier", loginFilter.trim());
      if (loginSuccessFilter !== "all") p.set("success", loginSuccessFilter);
      return (await api.get(`/security/login-attempts?${p.toString()}`)).data;
    },
  });

  const { data: auditLogs = [] } = useQuery<any[]>({
    queryKey: ["security-audit-logs", auditSearch, auditIp, auditAction],
    enabled: isCollegeAdmin && subTab === "audit",
    queryFn: async () => {
      const p = new URLSearchParams();
      if (auditSearch.trim()) p.set("search", auditSearch.trim());
      if (auditIp.trim()) p.set("ip_address", auditIp.trim());
      if (auditAction.trim()) p.set("action", auditAction.trim());
      return (await api.get(`/security/audit-logs?${p.toString()}`)).data;
    },
  });

  const refreshAll = () => {
    void refetchDash();
    void refetchAlerts();
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Card className="p-4">
          <div className="text-xs font-semibold text-slate-500">Open Alerts</div>
          <div className="mt-1 text-2xl font-black text-slate-900">{dash?.open_alerts ?? 0}</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs font-semibold text-slate-500">High / Critical</div>
          <div className="mt-1 text-2xl font-black text-red-600">{dash?.high_critical_alerts ?? 0}</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs font-semibold text-slate-500">Failed Logins (24h)</div>
          <div className="mt-1 text-2xl font-black text-amber-600">{dash?.failed_logins_24h ?? 0}</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs font-semibold text-slate-500">Locked Accounts</div>
          <div className="mt-1 text-2xl font-black text-red-700">{dash?.locked_accounts_count ?? 0}</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs font-semibold text-slate-500">Invalid QR (24h)</div>
          <div className="mt-1 text-2xl font-black text-amber-700">{dash?.invalid_qr_24h ?? 0}</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs font-semibold text-slate-500">Dup. Handovers (24h)</div>
          <div className="mt-1 text-2xl font-black text-rose-700">{dash?.duplicate_handover_24h ?? 0}</div>
        </Card>
      </div>

      {isCollegeAdmin && (dash?.locked_accounts?.length ?? 0) > 0 && (
        <Card className="border-red-200 bg-red-50/70 p-4 space-y-2">
          <div className="flex items-center gap-2 font-bold text-red-900 text-sm">
            <Lock className="h-4 w-4" /> Temporarily Locked Accounts (Brute-Force Protection)
          </div>
          <div className="space-y-2">
            {dash.locked_accounts.map((acc: any) => (
              <div
                key={acc.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-red-200 bg-white px-3 py-2 text-xs"
              >
                <div>
                  <span className="font-bold text-slate-900">{acc.full_name}</span> ({acc.email || acc.phone}) •{" "}
                  <span className="font-semibold text-red-700">{acc.failed_login_attempts} failed attempts</span>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    try {
                      await api.post(`/security/users/${acc.id}/unlock`);
                      pushToast("Account unlocked", "success");
                      refreshAll();
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  <Unlock className="h-3.5 w-3.5" /> Unlock Account
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={subTab === "alerts" ? "secondary" : "outline"} onClick={() => setSubTab("alerts")}>
          <ShieldAlert className="h-3.5 w-3.5" /> Security &amp; Fraud Alerts
        </Button>
        <Button size="sm" variant={subTab === "qr" ? "secondary" : "outline"} onClick={() => setSubTab("qr")}>
          <QrCode className="h-3.5 w-3.5" /> QR Verification Events
        </Button>
        {isCollegeAdmin && (
          <>
            <Button size="sm" variant={subTab === "logins" ? "secondary" : "outline"} onClick={() => setSubTab("logins")}>
              <Lock className="h-3.5 w-3.5" /> Login Attempts
            </Button>
            <Button size="sm" variant={subTab === "audit" ? "secondary" : "outline"} onClick={() => setSubTab("audit")}>
              <FileSearch className="h-3.5 w-3.5" /> Audit Log Explorer
            </Button>
          </>
        )}
      </div>

      {subTab === "alerts" && (
        <Card className="p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-bold text-slate-900 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600" /> Fraud &amp; Security Alerts ({alerts.length})
            </h3>
            <Select value={alertStatus} onChange={(e) => setAlertStatus(e.target.value)} className="w-40">
              <option value="open">Open Alerts</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
              <option value="dismissed">Dismissed</option>
              <option value="all">All Statuses</option>
            </Select>
          </div>

          {alerts.length === 0 ? (
            <div className="rounded-xl bg-slate-50 p-6 text-center text-xs text-slate-500">
              No security alerts matching filter.
            </div>
          ) : (
            <div className="space-y-2.5 text-xs">
              {alerts.map((al) => (
                <div key={al.id} className="rounded-xl border border-slate-200 p-3.5 space-y-2">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="space-y-0.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={al.severity === "critical" || al.severity === "high" ? "red" : "amber"}>
                          {al.severity.toUpperCase()}
                        </Badge>
                        <Badge tone={al.status === "open" ? "amber" : "green"}>{al.status}</Badge>
                        <span className="font-mono text-[11px] text-slate-500">{al.alert_type}</span>
                        {al.metadata?.occurrences > 1 && (
                          <Badge tone="slate">{al.metadata.occurrences}x hits</Badge>
                        )}
                      </div>
                      <div className="font-bold text-sm text-slate-900">{al.title}</div>
                      <div className="text-slate-600">{al.description}</div>
                      <div className="text-[11px] text-slate-400">
                        {new Date(al.created_at).toLocaleString()}
                        {al.ip_address ? ` • IP: ${al.ip_address}` : ""}
                        {al.canteen_name ? ` • ${al.canteen_name}` : ""}
                      </div>
                    </div>
                    {al.status === "open" && (
                      <div className="flex flex-wrap gap-1.5">
                        <Button
                          size="sm"
                          variant="success"
                          onClick={async () => {
                            try {
                              await api.post(`/security/alerts/${al.id}/resolve`, {
                                status: "resolved",
                                notes: "Reviewed and resolved from Security Console",
                              });
                              pushToast("Alert resolved", "success");
                              refreshAll();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Resolve
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            try {
                              await api.post(`/security/alerts/${al.id}/resolve`, {
                                status: "dismissed",
                                notes: "False positive / dismissed",
                              });
                              pushToast("Alert dismissed", "info");
                              refreshAll();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Dismiss
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {subTab === "qr" && (
        <Card className="p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-bold text-slate-900">QR Verification &amp; Handover Events</h3>
            <Select value={qrValidity} onChange={(e) => setQrValidity(e.target.value)} className="w-44">
              <option value="false">Rejected / Suspicious</option>
              <option value="true">Valid Scans</option>
              <option value="all">All Scans</option>
            </Select>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 pr-3">Time</th>
                  <th className="py-2 pr-3">Method</th>
                  <th className="py-2 pr-3">Result</th>
                  <th className="py-2 pr-3">Order / Token</th>
                  <th className="py-2 pr-3">Staff</th>
                  <th className="py-2 pr-3">Details</th>
                </tr>
              </thead>
              <tbody>
                {qrEvents.map((ev) => (
                  <tr key={ev.id} className="border-b border-slate-100">
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-500">
                      {new Date(ev.created_at).toLocaleString()}
                    </td>
                    <td className="py-2 pr-3 font-mono">{ev.verification_method}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={ev.is_valid ? "green" : "red"}>{ev.result_code}</Badge>
                    </td>
                    <td className="py-2 pr-3 font-mono">
                      {ev.order_number || "-"} {ev.pickup_token_code ? `(${ev.pickup_token_code})` : ""}
                    </td>
                    <td className="py-2 pr-3">{ev.staff_name || "-"}</td>
                    <td className="py-2 pr-3 text-slate-600">
                      {ev.details} {ev.presented_code_masked ? `[${ev.presented_code_masked}]` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {isCollegeAdmin && subTab === "logins" && (
        <Card className="p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-bold text-slate-900">Authentication Attempts Log</h3>
            <div className="flex flex-wrap gap-2">
              <Input
                value={loginFilter}
                onChange={(e) => setLoginFilter(e.target.value)}
                placeholder="Filter email or phone..."
                className="w-48"
              />
              <Select value={loginSuccessFilter} onChange={(e) => setLoginSuccessFilter(e.target.value)} className="w-36">
                <option value="false">Failed Only</option>
                <option value="true">Succeeded Only</option>
                <option value="all">All Attempts</option>
              </Select>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 pr-3">Time</th>
                  <th className="py-2 pr-3">Identifier</th>
                  <th className="py-2 pr-3">Outcome</th>
                  <th className="py-2 pr-3">IP Address</th>
                  <th className="py-2 pr-3">Reason</th>
                </tr>
              </thead>
              <tbody>
                {loginAttempts.map((la) => (
                  <tr key={la.id} className="border-b border-slate-100">
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-500">
                      {new Date(la.created_at).toLocaleString()}
                    </td>
                    <td className="py-2 pr-3 font-mono">{la.identifier}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={la.success ? "green" : "red"}>{la.success ? "SUCCESS" : "FAILED"}</Badge>
                    </td>
                    <td className="py-2 pr-3 font-mono">{la.ip_address || "-"}</td>
                    <td className="py-2 pr-3 text-slate-600">{la.failure_reason || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {isCollegeAdmin && subTab === "audit" && (
        <Card className="p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-bold text-slate-900">Filterable Security Audit Log</h3>
            <div className="flex flex-wrap gap-2">
              <Input value={auditAction} onChange={(e) => setAuditAction(e.target.value)} placeholder="Action..." className="w-40" />
              <Input value={auditIp} onChange={(e) => setAuditIp(e.target.value)} placeholder="IP address..." className="w-36" />
              <Input value={auditSearch} onChange={(e) => setAuditSearch(e.target.value)} placeholder="Entity/keyword..." className="w-44" />
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 pr-3">Time</th>
                  <th className="py-2 pr-3">Actor</th>
                  <th className="py-2 pr-3">Action</th>
                  <th className="py-2 pr-3">Target</th>
                  <th className="py-2 pr-3">IP</th>
                </tr>
              </thead>
              <tbody>
                {auditLogs.map((a) => (
                  <tr key={a.id} className="border-b border-slate-100">
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-500">
                      {new Date(a.created_at).toLocaleString()}
                    </td>
                    <td className="py-2 pr-3">{a.actor_label}</td>
                    <td className="py-2 pr-3 font-mono font-semibold">{a.action}</td>
                    <td className="py-2 pr-3 font-mono">
                      {a.entity_type}:{a.entity_id || "-"}
                    </td>
                    <td className="py-2 pr-3 font-mono">{a.ip_address || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
};
