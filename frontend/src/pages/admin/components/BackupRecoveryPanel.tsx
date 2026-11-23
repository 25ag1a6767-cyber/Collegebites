import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Archive, CheckCircle2, Download, HardDriveUpload, RefreshCw, ShieldCheck, AlertOctagon } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, useToast } from "../../../components/ui/Primitives";

export const BackupRecoveryPanel: React.FC<{
  downloadBlob: (url: string, filename: string) => Promise<void>;
}> = ({ downloadBlob }) => {
  const { pushToast } = useToast();
  const [creating, setCreating] = useState(false);
  const [confirmRestoreId, setConfirmRestoreId] = useState<string | null>(null);
  const [confirmPhrase, setConfirmPhrase] = useState("");
  const [autoEnabled, setAutoEnabled] = useState(true);
  const [freqHours, setFreqHours] = useState(24);
  const [retentionDays, setRetentionDays] = useState(30);
  const [maxBackups, setMaxBackups] = useState(30);

  const { data: dash, refetch: refetchDash } = useQuery<any>({
    queryKey: ["backup-dashboard"],
    queryFn: async () => (await api.get("/backups/dashboard")).data,
  });

  useEffect(() => {
    if (dash?.settings) {
      setAutoEnabled(Boolean(dash.settings.auto_backup_enabled));
      setFreqHours(Number(dash.settings.frequency_hours ?? 24));
      setRetentionDays(Number(dash.settings.retention_days ?? 30));
      setMaxBackups(Number(dash.settings.max_backups ?? 30));
    }
  }, [dash]);

  const handleCreateBackup = async () => {
    setCreating(true);
    try {
      const b = (await api.post("/backups", { trigger_type: "manual" })).data;
      pushToast(`Encrypted backup ${b.backup_code} created & verified`, "success");
      void refetchDash();
    } catch (err) {
      pushToast(getApiError(err), "error");
    } finally {
      setCreating(false);
    }
  };

  const backups = dash?.backups || [];
  const recoveryLogs = dash?.recovery_logs || [];

  return (
    <div className="space-y-5">
      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-extrabold text-slate-900 flex items-center gap-2">
              <Archive className="h-5 w-5 text-emerald-600" /> Automated Backup &amp; Disaster Recovery Vault
            </h2>
            <p className="text-xs text-slate-500">
              AES/Fernet encrypted snapshots with SHA-256 verification • Passwords &amp; gateway secrets are strictly excluded
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={handleCreateBackup} disabled={creating}>
              <HardDriveUpload className="h-3.5 w-3.5" /> {creating ? "Creating..." : "Create Encrypted Backup"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void refetchDash()}>
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Verified Snapshots</div>
            <div className="text-xl font-black text-emerald-700">
              {dash?.verified_backups ?? 0} / {dash?.total_backups ?? 0}
            </div>
          </div>
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Failed Runs</div>
            <div className="text-xl font-black text-red-600">{dash?.failed_backups ?? 0}</div>
          </div>
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Last Verified</div>
            <div className="text-xs font-bold text-slate-800 mt-1">
              {dash?.latest_verified?.created_at
                ? new Date(dash.latest_verified.created_at).toLocaleString()
                : "None yet"}
            </div>
          </div>
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Schedule Cadence</div>
            <div className="text-xs font-bold text-slate-800 mt-1">
              {autoEnabled ? `Every ${freqHours}h • Retain ${retentionDays}d` : "Auto-backup paused"}
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 p-3.5 flex flex-wrap items-end gap-3 text-xs">
          <label className="flex items-center gap-2 font-semibold cursor-pointer pb-1.5">
            <input type="checkbox" checked={autoEnabled} onChange={(e) => setAutoEnabled(e.target.checked)} />
            Auto-Backup Enabled
          </label>
          <div>
            <div className="text-[11px] text-slate-500 mb-1">Frequency (hours)</div>
            <Input
              type="number"
              min={1}
              max={168}
              value={freqHours}
              onChange={(e) => setFreqHours(Number(e.target.value))}
              className="w-24"
            />
          </div>
          <div>
            <div className="text-[11px] text-slate-500 mb-1">Retention (days)</div>
            <Input
              type="number"
              min={1}
              max={365}
              value={retentionDays}
              onChange={(e) => setRetentionDays(Number(e.target.value))}
              className="w-24"
            />
          </div>
          <div>
            <div className="text-[11px] text-slate-500 mb-1">Max Snapshots</div>
            <Input
              type="number"
              min={2}
              max={200}
              value={maxBackups}
              onChange={(e) => setMaxBackups(Number(e.target.value))}
              className="w-24"
            />
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              try {
                await api.put("/backups/settings", {
                  auto_backup_enabled: autoEnabled,
                  frequency_hours: freqHours,
                  retention_days: retentionDays,
                  max_backups: maxBackups,
                });
                pushToast("Backup schedule & retention policy saved", "success");
                void refetchDash();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Save Policy
          </Button>
        </div>
      </Card>

      <Card className="p-5 space-y-3">
        <h3 className="font-bold text-slate-900">Encrypted Backup Archives ({backups.length})</h3>
        {backups.length === 0 ? (
          <div className="rounded-xl bg-slate-50 p-6 text-center text-xs text-slate-500">
            No backups recorded yet. Click "Create Encrypted Backup" to generate an encrypted snapshot.
          </div>
        ) : (
          <div className="space-y-2.5 text-xs">
            {backups.map((b: any) => (
              <div key={b.id} className="rounded-xl border border-slate-200 p-3.5 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono font-bold text-slate-900">{b.backup_code}</span>
                      <Badge tone={b.status === "failed" ? "red" : b.integrity_verified ? "green" : "amber"}>
                        {b.integrity_verified ? "VERIFIED" : b.status.toUpperCase()}
                      </Badge>
                      <Badge tone="slate">{b.trigger_type}</Badge>
                      {b.is_encrypted && <Badge tone="blue">AES/Fernet Encrypted</Badge>}
                    </div>
                    <div className="text-[11px] text-slate-500 mt-1">
                      Size: {(b.size_bytes / 1024).toFixed(1)} KB • Rows: {b.total_rows} • SHA-256:{" "}
                      <span className="font-mono">{b.checksum_sha256.slice(0, 16)}...</span> •{" "}
                      {new Date(b.created_at).toLocaleString()}
                    </div>
                    {b.error_message && <div className="text-red-600 font-semibold mt-1">{b.error_message}</div>}
                  </div>

                  {b.status !== "failed" && (
                    <div className="flex flex-wrap gap-1.5">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={async () => {
                          try {
                            const res = (await api.post(`/backups/${b.id}/verify`)).data;
                            pushToast(`Integrity verified (${res.total_rows} rows across ${res.tables_count} tables)`, "success");
                            void refetchDash();
                          } catch (err) {
                            pushToast(getApiError(err), "error");
                          }
                        }}
                      >
                        <ShieldCheck className="h-3.5 w-3.5" /> Verify
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={async () => {
                          try {
                            const res = (await api.post(`/backups/${b.id}/restore`, { dry_run: true })).data;
                            pushToast(`Dry-run restore OK: ${res.total_rows} rows verified cleanly`, "success");
                            void refetchDash();
                          } catch (err) {
                            pushToast(getApiError(err), "error");
                          }
                        }}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" /> Dry-Run Restore
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void downloadBlob(`/backups/${b.id}/download`, `${b.backup_code}.cbk.enc`)}
                      >
                        <Download className="h-3.5 w-3.5" /> Encrypted
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => {
                          setConfirmRestoreId(confirmRestoreId === b.id ? null : b.id);
                          setConfirmPhrase("");
                        }}
                      >
                        Restore DB
                      </Button>
                    </div>
                  )}
                </div>

                {confirmRestoreId === b.id && (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-3 flex flex-wrap items-center gap-2">
                    <AlertOctagon className="h-4 w-4 text-red-700 shrink-0" />
                    <span className="text-red-900 font-semibold">
                      Production restore overwrites live tables cleanly after automatic pre-restore snapshot. Type{" "}
                      <code className="bg-white px-1 py-0.5 rounded">CONFIRM PRODUCTION RESTORE</code>:
                    </span>
                    <Input
                      value={confirmPhrase}
                      onChange={(e) => setConfirmPhrase(e.target.value)}
                      placeholder="CONFIRM PRODUCTION RESTORE"
                      className="w-60 bg-white"
                    />
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={async () => {
                        try {
                          const res = (
                            await api.post(`/backups/${b.id}/restore`, {
                              dry_run: false,
                              confirmation_phrase: confirmPhrase,
                            })
                          ).data;
                          pushToast(`Database restored from ${b.backup_code} (${res.total_rows} rows)`, "success");
                          setConfirmRestoreId(null);
                          setConfirmPhrase("");
                          void refetchDash();
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      Execute Restore
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-5 space-y-3">
        <h3 className="font-bold text-slate-900">Disaster Recovery &amp; Drill Logs ({recoveryLogs.length})</h3>
        {recoveryLogs.length === 0 ? (
          <div className="text-xs text-slate-500">No recovery tests or restores run yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 pr-3">Time</th>
                  <th className="py-2 pr-3">Backup Code</th>
                  <th className="py-2 pr-3">Target</th>
                  <th className="py-2 pr-3">Mode</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Scope</th>
                </tr>
              </thead>
              <tbody>
                {recoveryLogs.map((l: any) => (
                  <tr key={l.id} className="border-b border-slate-100">
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-500">
                      {new Date(l.started_at).toLocaleString()}
                    </td>
                    <td className="py-2 pr-3 font-mono">{l.backup_code || "-"}</td>
                    <td className="py-2 pr-3 font-mono">{l.target_env}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={l.dry_run ? "slate" : "amber"}>{l.dry_run ? "Dry-Run" : "Live Restore"}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge tone={l.verification_passed ? "green" : "red"}>{l.status}</Badge>
                    </td>
                    <td className="py-2 pr-3">{l.tables_count} tables / {l.total_rows} rows</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};
