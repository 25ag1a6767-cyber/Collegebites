import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  Download,
  Edit3,
  FileText,
  IndianRupee,
  PackageCheck,
  Plus,
  Search,
  Truck,
} from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../../components/ui/Primitives";

interface VendorProcurementTabProps {
  activeCanteenId: string;
  activeItems: any[];
  canApprovePo: boolean;
  onChanged: () => void;
}

export const VendorProcurementTab: React.FC<VendorProcurementTabProps> = ({
  activeCanteenId,
  activeItems,
  canApprovePo,
  onChanged,
}) => {
  const { pushToast } = useToast();
  const [vendorSearch, setVendorSearch] = useState("");
  const [vendorActiveFilter, setVendorActiveFilter] = useState<"all" | "true" | "false">("all");
  const [vendorProductFilter, setVendorProductFilter] = useState("");

  // Vendor form state
  const [supName, setSupName] = useState("");
  const [supContact, setSupContact] = useState("");
  const [supPhone, setSupPhone] = useState("");
  const [supEmail, setSupEmail] = useState("");
  const [supAddress, setSupAddress] = useState("");
  const [supGst, setSupGst] = useState("");
  const [supBusiness, setSupBusiness] = useState("");
  const [supProducts, setSupProducts] = useState("Raw Ingredients, Packaging Supplies");
  const [supTerms, setSupTerms] = useState("Net 15 Days");
  const [editingVendor, setEditingVendor] = useState<any | null>(null);
  const [statementVendorId, setStatementVendorId] = useState<string | null>(null);

  // PO creation state
  const [poSupplierId, setPoSupplierId] = useState("");
  const [poInitStatus, setPoInitStatus] = useState(canApprovePo ? "ordered" : "pending_approval");
  const [poExpectedDate, setPoExpectedDate] = useState("");
  const [poNotes, setPoNotes] = useState("");
  const [poLines, setPoLines] = useState<
    Array<{
      ingredient_id: string;
      item_name: string;
      unit: string;
      quantity_ordered: string;
      unit_cost: string;
      tax_rate_percent: string;
      expiry_date: string;
    }>
  >([
    {
      ingredient_id: "",
      item_name: "",
      unit: "kg",
      quantity_ordered: "25",
      unit_cost: "45.00",
      tax_rate_percent: "5.00",
      expiry_date: "",
    },
  ]);

  // GRN modal state
  const [grnPo, setGrnPo] = useState<any | null>(null);
  const [grnChallan, setGrnChallan] = useState("");
  const [grnNotes, setGrnNotes] = useState("");
  const [grnRows, setGrnRows] = useState<Record<string, { accepted: string; damaged: string; rejected: string; missing: string; expiry: string }>>({});

  // Vendor Payment state
  const [payVendorId, setPayVendorId] = useState("");
  const [payPoId, setPayPoId] = useState("");
  const [payAmount, setPayAmount] = useState("");
  const [payMethod, setPayMethod] = useState("bank_transfer");
  const [payRef, setPayRef] = useState("");
  const [payDocUrl, setPayDocUrl] = useState("");
  const [payNotes, setPayNotes] = useState("");

  const { data: vendors = [], refetch: refetchVendors } = useQuery<any[]>({
    queryKey: ["vendors-list", vendorSearch, vendorActiveFilter, vendorProductFilter],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (vendorSearch.trim()) qs.set("search", vendorSearch.trim());
      if (vendorActiveFilter !== "all") qs.set("is_active", vendorActiveFilter);
      if (vendorProductFilter.trim()) qs.set("product", vendorProductFilter.trim());
      return (await api.get(`/inventory/suppliers?${qs.toString()}`)).data;
    },
  });

  const { data: purchaseOrders = [], refetch: refetchPos } = useQuery<any[]>({
    queryKey: ["vendor-pos", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeCanteenId}/purchase-orders`)).data,
  });

  const { data: vendorPayments = [], refetch: refetchPayments } = useQuery<any[]>({
    queryKey: ["vendor-payments", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/inventory/vendor-payments?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: vendorStatement } = useQuery<any>({
    queryKey: ["vendor-statement", statementVendorId],
    enabled: Boolean(statementVendorId),
    queryFn: async () => (await api.get(`/inventory/suppliers/${statementVendorId}/statement`)).data,
  });

  const refreshProcurement = () => {
    refetchVendors();
    refetchPos();
    refetchPayments();
    onChanged();
  };

  const downloadPoPdf = async (po: any) => {
    try {
      const res = await api.get(`/inventory/purchase-orders/${po.id}/pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${po.po_number}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      pushToast(getApiError(err, "Failed to download PO PDF"), "error");
    }
  };

  const openGrnModal = (po: any) => {
    const initial: Record<string, { accepted: string; damaged: string; rejected: string; missing: string; expiry: string }> = {};
    for (const it of po.items || []) {
      const rem = Math.max(0, Number(it.quantity_ordered || 0) - Number(it.quantity_received || 0));
      initial[it.id] = {
        accepted: rem > 0 ? String(rem) : "0",
        damaged: "0",
        rejected: "0",
        missing: "0",
        expiry: it.expiry_date || "",
      };
    }
    setGrnRows(initial);
    setGrnChallan("");
    setGrnNotes("");
    setGrnPo(po);
  };

  const activeVendors = vendors.filter((v) => v.is_active);

  return (
    <div className="space-y-6">
      {/* Vendor Directory & Performance */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Truck className="h-4 w-4 text-slate-700" />
            {editingVendor ? `Edit Vendor: ${editingVendor.name}` : "Register Vendor / Supplier"}
          </h2>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <Input value={supName} onChange={(e) => setSupName(e.target.value)} placeholder="Vendor Name *" />
            <Input value={supContact} onChange={(e) => setSupContact(e.target.value)} placeholder="Contact Person" />
            <Input value={supPhone} onChange={(e) => setSupPhone(e.target.value)} placeholder="Phone Number" />
            <Input value={supEmail} onChange={(e) => setSupEmail(e.target.value)} placeholder="Email Address" />
            <Input value={supGst} onChange={(e) => setSupGst(e.target.value)} placeholder="GSTIN / Tax ID" />
            <Input value={supTerms} onChange={(e) => setSupTerms(e.target.value)} placeholder="Payment Terms" />
          </div>
          <Input value={supAddress} onChange={(e) => setSupAddress(e.target.value)} placeholder="Registered Address" />
          <Input value={supBusiness} onChange={(e) => setSupBusiness(e.target.value)} placeholder="Business Details / Bank IFSC / License" />
          <Input
            value={supProducts}
            onChange={(e) => setSupProducts(e.target.value)}
            placeholder="Supplied Products (comma-separated: Dairy, Packaging, Beverages)"
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={!supName.trim()}
              onClick={async () => {
                const payload = {
                  name: supName.trim(),
                  contact_person: supContact.trim() || null,
                  phone: supPhone.trim() || null,
                  email: supEmail.trim() || null,
                  address: supAddress.trim() || null,
                  gst_number: supGst.trim() || null,
                  business_details: supBusiness.trim() || null,
                  payment_terms: supTerms.trim() || null,
                  supplied_products: supProducts
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                };
                try {
                  if (editingVendor) {
                    await api.patch(`/inventory/suppliers/${editingVendor.id}`, payload);
                    pushToast("Vendor profile updated", "success");
                  } else {
                    await api.post("/inventory/suppliers", payload);
                    pushToast("Vendor registered", "success");
                  }
                  setEditingVendor(null);
                  setSupName("");
                  setSupContact("");
                  setSupPhone("");
                  setSupEmail("");
                  setSupAddress("");
                  setSupGst("");
                  setSupBusiness("");
                  refreshProcurement();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              {editingVendor ? "Update Vendor" : "Add Vendor"}
            </Button>
            {editingVendor && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setEditingVendor(null);
                  setSupName("");
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </Card>

        <Card className="p-5 lg:col-span-2 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-bold text-slate-900">Vendor Directory, Performance &amp; Balances ({vendors.length})</h2>
            <div className="flex flex-wrap gap-2">
              <div className="relative">
                <Search className="h-3.5 w-3.5 text-slate-400 absolute left-2.5 top-2.5" />
                <Input
                  value={vendorSearch}
                  onChange={(e) => setVendorSearch(e.target.value)}
                  placeholder="Search vendor, GST, phone..."
                  className="pl-8 w-48"
                />
              </div>
              <Input
                value={vendorProductFilter}
                onChange={(e) => setVendorProductFilter(e.target.value)}
                placeholder="Filter by product..."
                className="w-36"
              />
              <Select value={vendorActiveFilter} onChange={(e) => setVendorActiveFilter(e.target.value as any)}>
                <option value="all">All Vendors</option>
                <option value="true">Active Only</option>
                <option value="false">Inactive</option>
              </Select>
            </div>
          </div>

          <div className="overflow-x-auto max-h-80">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="p-2">Vendor</th>
                  <th className="p-2">Supplied Products</th>
                  <th className="p-2">POs &amp; Fulfillment</th>
                  <th className="p-2">Billed / Paid</th>
                  <th className="p-2">Outstanding</th>
                  <th className="p-2">Status</th>
                  <th className="p-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {vendors.map((v) => (
                  <tr key={v.id}>
                    <td className="p-2">
                      <div className="font-bold text-slate-900">{v.name}</div>
                      <div className="text-[11px] text-slate-500">
                        {v.contact_person || "—"} • {v.phone || "No phone"}
                      </div>
                      {v.gst_number && <div className="text-[10px] font-mono text-slate-400">GST: {v.gst_number}</div>}
                    </td>
                    <td className="p-2">
                      <div className="flex flex-wrap gap-1">
                        {(v.supplied_products || []).length === 0 ? (
                          <span className="text-slate-400">General</span>
                        ) : (
                          (v.supplied_products || []).map((p: string, idx: number) => (
                            <Badge key={idx} tone="blue">{p}</Badge>
                          ))
                        )}
                      </div>
                    </td>
                    <td className="p-2">
                      <div className="font-semibold">{v.total_purchase_orders || 0} POs ({v.fulfillment_rate_percent ?? 100}% fulfilled)</div>
                      {Number(v.total_damaged_rejected_qty || 0) > 0 && (
                        <div className="text-[10px] text-red-600">Damaged/Rejected: {v.total_damaged_rejected_qty}</div>
                      )}
                    </td>
                    <td className="p-2">
                      <div>Billed: ₹{v.total_billed_amount || "0.00"}</div>
                      <div className="text-emerald-700">Paid: ₹{v.total_paid_amount || "0.00"}</div>
                    </td>
                    <td className="p-2 font-extrabold text-amber-900">₹{v.outstanding_balance || "0.00"}</td>
                    <td className="p-2">
                      <Badge tone={v.is_active ? "green" : "red"}>{v.is_active ? "Active" : "Deactivated"}</Badge>
                    </td>
                    <td className="p-2">
                      <div className="flex flex-wrap gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setStatementVendorId(v.id)}
                        >
                          <FileText className="h-3 w-3" /> Statement
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            setEditingVendor(v);
                            setSupName(v.name || "");
                            setSupContact(v.contact_person || "");
                            setSupPhone(v.phone || "");
                            setSupEmail(v.email || "");
                            setSupAddress(v.address || "");
                            setSupGst(v.gst_number || "");
                            setSupBusiness(v.business_details || "");
                            setSupTerms(v.payment_terms || "");
                            setSupProducts((v.supplied_products || []).join(", "));
                          }}
                        >
                          <Edit3 className="h-3 w-3" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={async () => {
                            try {
                              await api.patch(`/inventory/suppliers/${v.id}`, { is_active: !v.is_active });
                              pushToast(`Vendor ${!v.is_active ? "activated" : "deactivated"}`, "info");
                              refreshProcurement();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          {v.is_active ? "Deactivate" : "Activate"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* Purchase Orders & Goods Receiving */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900">Create Purchase Order (PO)</h2>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <label className="font-bold text-slate-600 block mb-1">Active Vendor *</label>
              <Select value={poSupplierId || activeVendors[0]?.id || ""} onChange={(e) => setPoSupplierId(e.target.value)}>
                {activeVendors.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </Select>
            </div>
            <div>
              <label className="font-bold text-slate-600 block mb-1">Initial Lifecycle Status</label>
              <Select value={poInitStatus} onChange={(e) => setPoInitStatus(e.target.value)}>
                {canApprovePo && <option value="ordered">Ordered (Direct Issue)</option>}
                <option value="pending_approval">Pending Admin Approval</option>
                <option value="draft">Draft</option>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <label className="font-bold text-slate-600 block mb-1">Expected Delivery</label>
              <Input type="date" value={poExpectedDate} onChange={(e) => setPoExpectedDate(e.target.value)} />
            </div>
            <div>
              <label className="font-bold text-slate-600 block mb-1">PO Notes</label>
              <Input value={poNotes} onChange={(e) => setPoNotes(e.target.value)} placeholder="Delivery instructions..." />
            </div>
          </div>

          <div className="space-y-2 border-t border-slate-100 pt-2">
            <div className="flex items-center justify-between text-xs font-bold text-slate-700">
              <span>Order Line Items (Ingredients / Packaging / Beverages)</span>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setPoLines((prev) => [
                    ...prev,
                    {
                      ingredient_id: activeItems[0]?.ingredient_id || "",
                      item_name: "",
                      unit: "units",
                      quantity_ordered: "10",
                      unit_cost: "25.00",
                      tax_rate_percent: "5.00",
                      expiry_date: "",
                    },
                  ])
                }
              >
                <Plus className="h-3 w-3" /> Line
              </Button>
            </div>
            {poLines.map((line, idx) => (
              <div key={idx} className="rounded-xl border border-slate-200 p-2.5 space-y-2 text-xs">
                <div className="grid grid-cols-2 gap-2">
                  <Select
                    value={line.ingredient_id}
                    onChange={(e) => {
                      const val = e.target.value;
                      const matched = activeItems.find((a) => a.ingredient_id === val);
                      setPoLines((prev) =>
                        prev.map((l, i) =>
                          i === idx
                            ? {
                                ...l,
                                ingredient_id: val,
                                item_name: matched ? matched.name : l.item_name,
                                unit: matched ? matched.unit : l.unit,
                                unit_cost: matched ? String(matched.unit_cost) : l.unit_cost,
                              }
                            : l
                        )
                      );
                    }}
                  >
                    <option value="">Custom Packaging / Supply Item</option>
                    {activeItems.map((it) => (
                      <option key={it.ingredient_id} value={it.ingredient_id}>
                        {it.name} ({it.unit})
                      </option>
                    ))}
                  </Select>
                  <Input
                    value={line.item_name}
                    onChange={(e) =>
                      setPoLines((prev) => prev.map((l, i) => (i === idx ? { ...l, item_name: e.target.value } : l)))
                    }
                    placeholder="Item Name (if non-ingredient)"
                  />
                </div>
                <div className="grid grid-cols-4 gap-1.5">
                  <Input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={line.quantity_ordered}
                    onChange={(e) =>
                      setPoLines((prev) => prev.map((l, i) => (i === idx ? { ...l, quantity_ordered: e.target.value } : l)))
                    }
                    placeholder="Qty"
                  />
                  <Input
                    value={line.unit}
                    onChange={(e) =>
                      setPoLines((prev) => prev.map((l, i) => (i === idx ? { ...l, unit: e.target.value } : l)))
                    }
                    placeholder="Unit"
                  />
                  <Input
                    type="number"
                    min="0"
                    step="0.01"
                    value={line.unit_cost}
                    onChange={(e) =>
                      setPoLines((prev) => prev.map((l, i) => (i === idx ? { ...l, unit_cost: e.target.value } : l)))
                    }
                    placeholder="Rate ₹"
                  />
                  <Input
                    type="number"
                    min="0"
                    step="0.5"
                    value={line.tax_rate_percent}
                    onChange={(e) =>
                      setPoLines((prev) => prev.map((l, i) => (i === idx ? { ...l, tax_rate_percent: e.target.value } : l)))
                    }
                    placeholder="Tax %"
                  />
                </div>
              </div>
            ))}
          </div>

          <Button
            className="w-full"
            disabled={activeVendors.length === 0}
            onClick={async () => {
              const supId = poSupplierId || activeVendors[0]?.id;
              if (!supId) return;
              try {
                await api.post("/inventory/purchase-orders", {
                  canteen_id: activeCanteenId,
                  supplier_id: supId,
                  initial_status: poInitStatus,
                  expected_delivery_date: poExpectedDate || null,
                  notes: poNotes.trim() || null,
                  items: poLines.map((l) => ({
                    ingredient_id: l.ingredient_id || (activeItems[0]?.ingredient_id ?? null),
                    item_name: l.item_name.trim() || undefined,
                    unit: l.unit.trim() || "units",
                    quantity_ordered: l.quantity_ordered,
                    unit_cost: l.unit_cost,
                    tax_rate_percent: l.tax_rate_percent || "0.00",
                    expiry_date: l.expiry_date || null,
                  })),
                });
                pushToast("Purchase order generated", "success");
                setPoNotes("");
                refreshProcurement();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Generate Purchase Order
          </Button>
        </Card>

        <Card className="p-5 lg:col-span-2 space-y-3">
          <h2 className="font-bold text-slate-900">Purchase Orders &amp; Goods Receiving ({purchaseOrders.length})</h2>
          <div className="space-y-2.5 max-h-96 overflow-y-auto">
            {purchaseOrders.length === 0 ? (
              <div className="text-xs text-slate-500">No purchase orders created yet.</div>
            ) : (
              purchaseOrders.map((po) => (
                <div key={po.id} className="rounded-xl border border-slate-200 p-3 text-xs space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-extrabold text-slate-900">{po.po_number}</span>
                        <Badge
                          tone={
                            po.status === "received"
                              ? "green"
                              : po.status === "cancelled"
                              ? "red"
                              : po.status === "partial" || po.status === "partially_received"
                              ? "blue"
                              : "amber"
                          }
                        >
                          {(po.lifecycle_status || po.status).toUpperCase()}
                        </Badge>
                        <span className="font-semibold text-slate-700">{po.supplier_name}</span>
                      </div>
                      <div className="text-[11px] text-slate-500">
                        Subtotal: ₹{po.subtotal_amount || po.total_cost} • Tax: ₹{po.tax_amount || "0.00"} •{" "}
                        <strong>Total: ₹{po.total_cost}</strong> • Paid: ₹{po.paid_amount || "0.00"} • Outstanding: ₹{po.outstanding_amount || po.total_cost}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => downloadPoPdf(po)}>
                        <Download className="h-3 w-3" /> PO PDF
                      </Button>
                      {po.status === "draft" && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            try {
                              await api.post(`/inventory/purchase-orders/${po.id}/status`, { status: "pending_approval" });
                              pushToast("Submitted for approval", "info");
                              refreshProcurement();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Submit
                        </Button>
                      )}
                      {po.status === "pending_approval" && canApprovePo && (
                        <Button
                          size="sm"
                          variant="success"
                          onClick={async () => {
                            try {
                              await api.post(`/inventory/purchase-orders/${po.id}/status`, { status: "approved" });
                              pushToast("Purchase Order Approved", "success");
                              refreshProcurement();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Approve PO
                        </Button>
                      )}
                      {po.status === "approved" && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={async () => {
                            try {
                              await api.post(`/inventory/purchase-orders/${po.id}/status`, { status: "ordered" });
                              pushToast("PO dispatched to vendor", "success");
                              refreshProcurement();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Mark Ordered
                        </Button>
                      )}
                      {["approved", "ordered", "partial", "partially_received"].includes(po.status) && (
                        <Button size="sm" variant="success" onClick={() => openGrnModal(po)}>
                          <PackageCheck className="h-3.5 w-3.5" /> Receive Goods (GRN)
                        </Button>
                      )}
                      {!["received", "cancelled"].includes(po.status) && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={async () => {
                            try {
                              await api.post(`/inventory/purchase-orders/${po.id}/cancel?reason=Cancelled%20by%20manager`);
                              pushToast(`Cancelled ${po.po_number}`, "info");
                              refreshProcurement();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  </div>
                  {(po.items || []).length > 0 && (
                    <div className="grid gap-1 pt-1 border-t border-slate-100 text-[11px] text-slate-600">
                      {(po.items || []).map((it: any) => (
                        <div key={it.id} className="flex flex-wrap justify-between">
                          <span>
                            <strong>{it.item_name}</strong>: Ordered {it.quantity_ordered} {it.unit} @ ₹{it.unit_cost} (+{it.tax_rate_percent}% tax)
                          </span>
                          <span>
                            Accepted: <strong className="text-emerald-700">{it.quantity_received}</strong>
                            {Number(it.quantity_damaged || 0) > 0 && <span className="text-red-600 ml-2">Damaged: {it.quantity_damaged}</span>}
                            {Number(it.quantity_rejected || 0) > 0 && <span className="text-amber-700 ml-2">Rejected: {it.quantity_rejected}</span>}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Vendor Payments & Verification */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <IndianRupee className="h-4 w-4 text-slate-700" /> Record Vendor Payment
          </h2>
          <div className="space-y-2 text-xs">
            <Select value={payVendorId || vendors[0]?.id || ""} onChange={(e) => setPayVendorId(e.target.value)}>
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} (Due: ₹{v.outstanding_balance || "0.00"})
                </option>
              ))}
            </Select>
            <Select value={payPoId} onChange={(e) => setPayPoId(e.target.value)}>
              <option value="">General Account Payment (No specific PO)</option>
              {purchaseOrders
                .filter((p) => p.supplier_id === (payVendorId || vendors[0]?.id) && p.status !== "cancelled")
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.po_number} — Due ₹{p.outstanding_amount}
                  </option>
                ))}
            </Select>
            <div className="grid grid-cols-2 gap-2">
              <Input
                type="number"
                min="1"
                step="0.01"
                value={payAmount}
                onChange={(e) => setPayAmount(e.target.value)}
                placeholder="Amount ₹ *"
              />
              <Select value={payMethod} onChange={(e) => setPayMethod(e.target.value)}>
                <option value="bank_transfer">Bank Transfer</option>
                <option value="neft_rtgs">NEFT / RTGS</option>
                <option value="upi">Corporate UPI</option>
                <option value="cheque">Cheque</option>
              </Select>
            </div>
            <Input
              value={payRef}
              onChange={(e) => setPayRef(e.target.value)}
              placeholder="UTR / Transaction Reference (Required to verify)"
            />
            <Input
              value={payDocUrl}
              onChange={(e) => setPayDocUrl(e.target.value)}
              placeholder="Invoice / Payment Receipt Document URL (Optional)"
            />
            <Input value={payNotes} onChange={(e) => setPayNotes(e.target.value)} placeholder="Notes" />
            <Button
              className="w-full"
              disabled={!payAmount || vendors.length === 0}
              onClick={async () => {
                try {
                  await api.post("/inventory/vendor-payments", {
                    supplier_id: payVendorId || vendors[0]?.id,
                    canteen_id: activeCanteenId,
                    purchase_order_id: payPoId || null,
                    amount: payAmount,
                    payment_method: payMethod,
                    payment_reference: payRef.trim() || null,
                    document_url: payDocUrl.trim() || null,
                    notes: payNotes.trim() || null,
                  });
                  setPayAmount("");
                  setPayRef("");
                  setPayDocUrl("");
                  setPayNotes("");
                  pushToast("Vendor payment recorded", "success");
                  refreshProcurement();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Save Vendor Payment
            </Button>
          </div>
        </Card>

        <Card className="p-5 lg:col-span-2 space-y-3">
          <h2 className="font-bold text-slate-900">Vendor Payment Ledger ({vendorPayments.length})</h2>
          <div className="overflow-x-auto max-h-72">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="p-2">Payment #</th>
                  <th className="p-2">Vendor / PO</th>
                  <th className="p-2">Amount</th>
                  <th className="p-2">Method &amp; UTR Ref</th>
                  <th className="p-2">Status</th>
                  <th className="p-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {vendorPayments.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="p-4 text-center text-slate-500">
                      No vendor payments recorded yet.
                    </td>
                  </tr>
                ) : (
                  vendorPayments.map((vp) => (
                    <tr key={vp.id}>
                      <td className="p-2 font-mono font-bold">{vp.payment_number}</td>
                      <td className="p-2">
                        <div className="font-semibold">{vp.supplier_name}</div>
                        <div className="text-[10px] text-slate-400">{vp.po_number || "Account Settlement"}</div>
                      </td>
                      <td className="p-2 font-extrabold text-slate-900">₹{vp.amount}</td>
                      <td className="p-2">
                        <div className="uppercase text-[10px] font-bold">{vp.payment_method}</div>
                        <div className="font-mono text-[11px]">{vp.payment_reference || "Pending UTR"}</div>
                      </td>
                      <td className="p-2">
                        <Badge tone={vp.status === "verified" ? "green" : "amber"}>
                          {vp.status === "verified" ? "Verified" : "Pending Verification"}
                        </Badge>
                      </td>
                      <td className="p-2">
                        {vp.status !== "verified" && canApprovePo && (
                          <Button
                            size="sm"
                            variant="success"
                            onClick={async () => {
                              const ref = window.prompt("Enter verified UTR / Bank Payment Reference:", vp.payment_reference || "");
                              if (!ref || !ref.trim()) return;
                              try {
                                await api.post(`/inventory/vendor-payments/${vp.id}/verify`, {
                                  payment_reference: ref.trim(),
                                });
                                pushToast("Vendor payment verified", "success");
                                refreshProcurement();
                              } catch (err) {
                                pushToast(getApiError(err), "error");
                              }
                            }}
                          >
                            <CheckCircle2 className="h-3 w-3" /> Verify
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* Goods Receiving Note (GRN) Modal */}
      <Modal
        open={Boolean(grnPo)}
        onClose={() => setGrnPo(null)}
        title={`Goods Receiving Note (GRN) — ${grnPo?.po_number || ""}`}
        maxWidth="max-w-2xl"
      >
        {grnPo && (
          <div className="space-y-3 text-xs">
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-2.5 text-emerald-950">
              Only <strong>Accepted (Verified)</strong> quantities update live inventory stock and FEFO batches. Damaged, rejected, and missing quantities are logged on the GRN and vendor quality scorecard.
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input
                value={grnChallan}
                onChange={(e) => setGrnChallan(e.target.value)}
                placeholder="Delivery Challan / Vendor Invoice Ref"
              />
              <Input
                value={grnNotes}
                onChange={(e) => setGrnNotes(e.target.value)}
                placeholder="Inspection Notes"
              />
            </div>
            <div className="space-y-2 max-h-72 overflow-y-auto">
              {(grnPo.items || []).map((it: any) => {
                const rem = Math.max(0, Number(it.quantity_ordered || 0) - Number(it.quantity_received || 0));
                const r = grnRows[it.id] || { accepted: String(rem), damaged: "0", rejected: "0", missing: "0", expiry: "" };
                return (
                  <div key={it.id} className="rounded-xl border border-slate-200 p-2.5 space-y-2">
                    <div className="flex justify-between font-bold text-slate-900">
                      <span>{it.item_name} ({it.unit})</span>
                      <span>Ordered: {it.quantity_ordered} • Already Received: {it.quantity_received} • Open: {rem}</span>
                    </div>
                    <div className="grid grid-cols-5 gap-1.5">
                      <div>
                        <label className="block text-[10px] font-bold text-emerald-800">Accepted Qty</label>
                        <Input
                          type="number"
                          min="0"
                          max={rem}
                          step="0.01"
                          value={r.accepted}
                          onChange={(e) =>
                            setGrnRows((prev) => ({ ...prev, [it.id]: { ...r, accepted: e.target.value } }))
                          }
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] font-bold text-red-700">Damaged</label>
                        <Input
                          type="number"
                          min="0"
                          step="0.01"
                          value={r.damaged}
                          onChange={(e) =>
                            setGrnRows((prev) => ({ ...prev, [it.id]: { ...r, damaged: e.target.value } }))
                          }
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] font-bold text-amber-700">Rejected</label>
                        <Input
                          type="number"
                          min="0"
                          step="0.01"
                          value={r.rejected}
                          onChange={(e) =>
                            setGrnRows((prev) => ({ ...prev, [it.id]: { ...r, rejected: e.target.value } }))
                          }
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] font-bold text-slate-600">Missing</label>
                        <Input
                          type="number"
                          min="0"
                          step="0.01"
                          value={r.missing}
                          onChange={(e) =>
                            setGrnRows((prev) => ({ ...prev, [it.id]: { ...r, missing: e.target.value } }))
                          }
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] font-bold text-slate-600">Batch Expiry</label>
                        <Input
                          type="date"
                          value={r.expiry}
                          onChange={(e) =>
                            setGrnRows((prev) => ({ ...prev, [it.id]: { ...r, expiry: e.target.value } }))
                          }
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setGrnPo(null)}>Cancel</Button>
              <Button
                size="sm"
                variant="success"
                onClick={async () => {
                  try {
                    const received_items = (grnPo.items || []).map((it: any) => {
                      const r = grnRows[it.id] || { accepted: "0", damaged: "0", rejected: "0", missing: "0", expiry: "" };
                      return {
                        po_item_id: it.id,
                        ingredient_id: it.ingredient_id || null,
                        quantity_received: r.accepted || "0",
                        quantity_damaged: r.damaged || "0",
                        quantity_rejected: r.rejected || "0",
                        quantity_missing: r.missing || "0",
                        expiry_date: r.expiry || null,
                      };
                    });
                    await api.post(`/inventory/purchase-orders/${grnPo.id}/receive`, {
                      delivery_challan_ref: grnChallan.trim() || null,
                      notes: grnNotes.trim() || null,
                      received_items,
                    });
                    setGrnPo(null);
                    pushToast("GRN recorded & verified inventory stock updated!", "success");
                    refreshProcurement();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Confirm Goods Receipt
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Vendor Account Statement Modal */}
      <Modal
        open={Boolean(statementVendorId)}
        onClose={() => setStatementVendorId(null)}
        title={`Vendor Account Statement — ${vendorStatement?.vendor?.name || ""}`}
        maxWidth="max-w-2xl"
      >
        {vendorStatement ? (
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-3 gap-2 rounded-xl bg-slate-50 p-3">
              <div>
                <div className="text-slate-500">Total Billed (POs)</div>
                <div className="text-sm font-extrabold text-slate-900">₹{vendorStatement.vendor.total_billed_amount}</div>
              </div>
              <div>
                <div className="text-slate-500">Total Verified Paid</div>
                <div className="text-sm font-extrabold text-emerald-700">₹{vendorStatement.vendor.total_paid_amount}</div>
              </div>
              <div>
                <div className="text-slate-500">Closing Balance Due</div>
                <div className="text-sm font-extrabold text-amber-900">₹{vendorStatement.vendor.outstanding_balance}</div>
              </div>
            </div>
            <div className="max-h-72 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-100 text-left">
                  <tr>
                    <th className="p-2">Date</th>
                    <th className="p-2">Type</th>
                    <th className="p-2">Reference</th>
                    <th className="p-2">Billed (Dr)</th>
                    <th className="p-2">Paid (Cr)</th>
                    <th className="p-2">Balance</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(vendorStatement.ledger || []).map((row: any, i: number) => (
                    <tr key={i}>
                      <td className="p-2">{(row.timestamp || "").slice(0, 10)}</td>
                      <td className="p-2 uppercase font-semibold">{row.entry_type.replace("_", " ")}</td>
                      <td className="p-2 font-mono">{row.reference}</td>
                      <td className="p-2">₹{row.debit_billed}</td>
                      <td className="p-2 text-emerald-700">₹{row.credit_paid}</td>
                      <td className="p-2 font-bold">₹{row.running_balance}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="text-xs text-slate-500 py-4">Loading vendor statement...</div>
        )}
      </Modal>
    </div>
  );
};
