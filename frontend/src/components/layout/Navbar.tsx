import React, { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  ChefHat,
  CreditCard,
  LayoutDashboard,
  LogIn,
  LogOut,
  Monitor,
  Package,
  QrCode,
  ShoppingBag,
  Tv,
  User as UserIcon,
  UtensilsCrossed,
} from "lucide-react";
import { api } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, CartSummary, CollegeSettings } from "../../types";
import { Badge, Button, crowdBadgeTone } from "../ui/Primitives";

export const Navbar: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user, logout, selectedCanteenId, setSelectedCanteen } = useAppStore();
  const [notifOpen, setNotifOpen] = useState(false);

  useEffect(() => {
    if (!user?.id) return;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`${proto}://${window.location.host}/api/v1/ws/notifications/${user.id}`);
      ws.onmessage = () => {
        qc.invalidateQueries({ queryKey: ["notifications-my"] });
        qc.invalidateQueries({ queryKey: ["my-orders"] });
      };
    } catch {
      // polling fallback handles it
    }
    return () => ws?.close();
  }, [user?.id, qc]);

  const { data: college } = useQuery<CollegeSettings>({
    queryKey: ["college-settings"],
    queryFn: async () => (await api.get("/canteens/college")).data,
  });

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const activeCanteen = canteens.find((c) => c.id === selectedCanteenId) || canteens[0];

  const { data: cart } = useQuery<CartSummary>({
    queryKey: ["cart", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => (await api.get(`/carts?canteen_id=${activeCanteen!.id}`)).data,
  });

  const { data: notifications = [] } = useQuery<any[]>({
    queryKey: ["notifications-my"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/notifications/my")).data,
  });

  const unreadCount = notifications.filter((n) => !n.is_read).length;
  const cartQty = cart?.items?.reduce((s, i) => s + i.quantity, 0) || 0;
  const roles = new Set(user?.roles || []);
  const isStaff = (r: string[]) => roles.has("super_admin") || r.some((x) => roles.has(x));

  if (location.pathname.startsWith("/board") || location.pathname.startsWith("/kiosk")) {
    return null;
  }

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur-md no-print">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-4">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-orange-500 to-red-600 text-white shadow-md">
              <UtensilsCrossed className="h-5 w-5" />
            </div>
            <div>
              <div className="text-lg font-extrabold tracking-tight text-slate-900">CollegeBites</div>
              <div className="text-[11px] font-medium text-slate-500">
                {college?.college_name || "Campus Smart Canteen"}
              </div>
            </div>
          </Link>

          {canteens.length > 0 && (
            <div className="hidden md:flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1.5">
              <select
                value={activeCanteen?.id || ""}
                onChange={(e) => setSelectedCanteen(e.target.value)}
                className="bg-transparent text-xs font-bold text-slate-800 focus:outline-none"
                aria-label="Select Canteen"
              >
                {canteens.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              {activeCanteen && (
                <Badge tone={crowdBadgeTone(activeCanteen.crowd_level)}>
                  {activeCanteen.crowd_level.replace("_", " ")} • ~{activeCanteen.estimated_wait_minutes}m
                </Badge>
              )}
            </div>
          )}
        </div>

        <nav className="flex flex-wrap items-center gap-1.5">
          <Link to="/" className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100">
            Menu
          </Link>
          <Link to="/orders" className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100">
            Orders
          </Link>
          <Link to="/support" className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100">
            Support
          </Link>
          <Link
            to="/board"
            className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            <Tv className="h-3.5 w-3.5" /> Token Board
          </Link>

          {isStaff(["kitchen_staff", "canteen_manager", "college_admin"]) && (
            <Link
              to="/kitchen"
              className="inline-flex items-center gap-1 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-800 hover:bg-amber-100"
            >
              <ChefHat className="h-3.5 w-3.5" /> Kitchen
            </Link>
          )}
          {isStaff(["cashier", "canteen_manager", "college_admin"]) && (
            <Link
              to="/cashier"
              className="inline-flex items-center gap-1 rounded-lg bg-sky-50 px-2.5 py-1.5 text-xs font-semibold text-sky-800 hover:bg-sky-100"
            >
              <CreditCard className="h-3.5 w-3.5" /> Cashier POS
            </Link>
          )}
          {isStaff(["pickup_staff", "cashier", "canteen_manager", "college_admin"]) && (
            <Link
              to="/pickup"
              className="inline-flex items-center gap-1 rounded-lg bg-emerald-50 px-2.5 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-100"
            >
              <QrCode className="h-3.5 w-3.5" /> Pickup Scan
            </Link>
          )}
          {isStaff(["inventory_manager", "canteen_manager", "college_admin"]) && (
            <Link
              to="/inventory"
              className="inline-flex items-center gap-1 rounded-lg bg-purple-50 px-2.5 py-1.5 text-xs font-semibold text-purple-800 hover:bg-purple-100"
            >
              <Package className="h-3.5 w-3.5" /> Inventory
            </Link>
          )}
          {isStaff(["canteen_manager", "college_admin"]) && (
            <Link
              to="/admin"
              className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
            >
              <LayoutDashboard className="h-3.5 w-3.5" /> Admin
            </Link>
          )}
          {college?.kiosk_enabled && (
            <Link
              to="/kiosk"
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
            >
              <Monitor className="h-3.5 w-3.5" /> Kiosk
            </Link>
          )}
        </nav>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate("/checkout")} className="relative">
            <ShoppingBag className="h-4 w-4 text-orange-600" />
            <span>Cart</span>
            {cartQty > 0 && (
              <span className="ml-0.5 rounded-full bg-orange-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                {cartQty}
              </span>
            )}
          </Button>

          {user ? (
            <>
              <div className="relative">
                <Button variant="ghost" size="sm" onClick={() => setNotifOpen((o) => !o)} className="relative" aria-label="Notifications">
                  <Bell className="h-4 w-4" />
                  {unreadCount > 0 && (
                    <span className="absolute -right-0.5 -top-0.5 h-4 w-4 rounded-full bg-red-600 text-[10px] font-bold text-white flex items-center justify-center">
                      {unreadCount}
                    </span>
                  )}
                </Button>
                {notifOpen && (
                  <div className="absolute right-0 mt-2 w-80 rounded-2xl border border-slate-200 bg-white p-3 shadow-xl z-50">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-2">
                      <span className="text-xs font-extrabold text-slate-900">Notifications ({unreadCount} unread)</span>
                      <button
                        type="button"
                        onClick={() => {
                          setNotifOpen(false);
                          navigate("/profile");
                        }}
                        className="text-[11px] font-bold text-orange-600"
                      >
                        Manage
                      </button>
                    </div>
                    <div className="space-y-1.5 max-h-60 overflow-y-auto text-xs">
                      {notifications.length === 0 ? (
                        <div className="py-3 text-center text-slate-400">No notifications yet.</div>
                      ) : (
                        notifications.slice(0, 6).map((n) => (
                          <div
                            key={n.id}
                            className={`rounded-xl border p-2 ${
                              n.is_read ? "border-slate-100 bg-white" : "border-orange-200 bg-orange-50/50"
                            }`}
                          >
                            <div className="font-bold text-slate-900">{n.title}</div>
                            <div className="text-slate-600 mt-0.5 line-clamp-2">{n.message}</div>
                            {!n.is_read && (
                              <button
                                type="button"
                                onClick={async () => {
                                  await api.post(`/notifications/${n.id}/read`);
                                  qc.invalidateQueries({ queryKey: ["notifications-my"] });
                                }}
                                className="mt-1 text-[10px] font-bold text-orange-700"
                              >
                                Mark read
                              </button>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>
              <Button variant="ghost" size="sm" onClick={() => navigate("/profile")}>
                <UserIcon className="h-4 w-4" />
                <span className="hidden sm:inline">{user.full_name.split(" ")[0]}</span>
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    await api.post("/auth/logout");
                  } catch {
                    // ignore
                  }
                  logout();
                  navigate("/");
                }}
              >
                <LogOut className="h-3.5 w-3.5" />
              </Button>
            </>
          ) : (
            <Button variant="primary" size="sm" onClick={() => navigate("/login")}>
              <LogIn className="h-3.5 w-3.5" /> Sign In
            </Button>
          )}
        </div>
      </div>
    </header>
  );
};
