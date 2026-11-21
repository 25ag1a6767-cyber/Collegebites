import React from "react";
import { Link, useLocation } from "react-router-dom";
import { LifeBuoy, QrCode, ReceiptText, User, UtensilsCrossed } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";

const HIDDEN_PREFIXES = ["/board", "/kiosk", "/kitchen", "/cashier", "/pickup", "/inventory", "/admin", "/login", "/register"];

export const MobileAppNav: React.FC = () => {
  const { pathname } = useLocation();
  const { user } = useAppStore();

  if (HIDDEN_PREFIXES.some((p) => pathname.startsWith(p))) {
    return null;
  }

  const tabs = [
    { to: "/", label: "Menu", icon: UtensilsCrossed, match: (p: string) => p === "/" || p === "/checkout" },
    { to: "/scan", label: "Scan QR", icon: QrCode, match: (p: string) => p.startsWith("/scan") },
    { to: "/orders", label: "Orders", icon: ReceiptText, match: (p: string) => p.startsWith("/orders") },
    { to: "/support", label: "Support", icon: LifeBuoy, match: (p: string) => p.startsWith("/support") },
    {
      to: user ? "/profile" : "/login",
      label: user ? "Profile" : "Sign In",
      icon: User,
      match: (p: string) => p.startsWith("/profile"),
    },
  ];

  return (
    <nav
      aria-label="Mobile Customer Navigation"
      className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-slate-200 bg-white/95 backdrop-blur-md shadow-[0_-4px_20px_rgba(15,23,42,0.06)] no-print pb-[env(safe-area-inset-bottom)]"
    >
      <div className="grid grid-cols-5">
        {tabs.map((tab) => {
          const active = tab.match(pathname);
          const Icon = tab.icon;
          return (
            <Link
              key={tab.label}
              to={tab.to}
              className={`flex flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-bold transition-colors ${
                active ? "text-orange-600" : "text-slate-500 hover:text-slate-800"
              }`}
            >
              <Icon className={`h-5 w-5 ${active ? "stroke-[2.5]" : ""}`} />
              <span>{tab.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
};
