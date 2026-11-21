import React from "react";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Navbar } from "./components/layout/Navbar";
import { Button, Card, ToastProvider } from "./components/ui/Primitives";
import { useAppStore } from "./store/useAppStore";
import { AuthPage } from "./pages/auth/AuthPage";
import { HomePage } from "./pages/customer/HomePage";
import { ScanQRPage } from "./pages/customer/ScanQRPage";
import { CheckoutPage } from "./pages/customer/CheckoutPage";
import { OrderTrackingPage } from "./pages/customer/OrderTrackingPage";
import { MyOrdersPage } from "./pages/customer/MyOrdersPage";
import { ProfilePage } from "./pages/customer/ProfilePage";
import { SupportPage } from "./pages/customer/SupportPage";
import { KitchenDisplayPage } from "./pages/kitchen/KitchenDisplayPage";
import { CashierPOSPage } from "./pages/cashier/CashierPOSPage";
import { PickupScannerPage } from "./pages/pickup/PickupScannerPage";
import { TokenBoardPage } from "./pages/board/TokenBoardPage";
import { InventoryPage } from "./pages/inventory/InventoryPage";
import { AdminConsolePage } from "./pages/admin/AdminConsolePage";
import { KioskPage } from "./pages/kiosk/KioskPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 10_000,
    },
  },
});

const RequireRole: React.FC<{ allowed: string[]; children: React.ReactNode }> = ({ allowed, children }) => {
  const user = useAppStore((s) => s.user);
  if (!user) {
    return (
      <div className="mx-auto max-w-md px-4 py-14">
        <Card className="p-6 text-center space-y-3">
          <div className="text-lg font-extrabold text-slate-900">Staff Sign-In Required</div>
          <p className="text-xs text-slate-500">Sign in with an authorized campus staff account to access this workspace.</p>
          <Link to="/login">
            <Button variant="primary" size="sm">Sign In</Button>
          </Link>
        </Card>
      </div>
    );
  }
  const roles = user.roles || [];
  const authorized = roles.includes("super_admin") || allowed.some((r) => roles.includes(r));
  if (!authorized) {
    return (
      <div className="mx-auto max-w-md px-4 py-14">
        <Card className="p-6 text-center space-y-3">
          <div className="text-lg font-extrabold text-slate-900">Access Restricted</div>
          <p className="text-xs text-slate-500">
            Your account does not hold the required role ({allowed.join(", ")}) for this workspace.
          </p>
          <Link to="/">
            <Button variant="outline" size="sm">Return to Menu</Button>
          </Link>
        </Card>
      </div>
    );
  }
  return <>{children}</>;
};

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <div className="min-h-screen bg-slate-50 text-slate-900">
            <Navbar />
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/login" element={<AuthPage initialMode="login" />} />
              <Route path="/register" element={<AuthPage initialMode="register" />} />
              <Route path="/scan/:code" element={<ScanQRPage />} />
              <Route path="/checkout" element={<CheckoutPage />} />
              <Route path="/orders" element={<MyOrdersPage />} />
              <Route path="/orders/:orderNumber" element={<OrderTrackingPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/support" element={<SupportPage />} />
              <Route
                path="/kitchen"
                element={
                  <RequireRole allowed={["kitchen_staff", "canteen_manager", "college_admin"]}>
                    <KitchenDisplayPage />
                  </RequireRole>
                }
              />
              <Route
                path="/cashier"
                element={
                  <RequireRole allowed={["cashier", "canteen_manager", "college_admin"]}>
                    <CashierPOSPage />
                  </RequireRole>
                }
              />
              <Route
                path="/pickup"
                element={
                  <RequireRole allowed={["pickup_staff", "cashier", "canteen_manager", "college_admin"]}>
                    <PickupScannerPage />
                  </RequireRole>
                }
              />
              <Route
                path="/pickup/verify"
                element={
                  <RequireRole allowed={["pickup_staff", "cashier", "canteen_manager", "college_admin"]}>
                    <PickupScannerPage />
                  </RequireRole>
                }
              />
              <Route path="/board" element={<TokenBoardPage />} />
              <Route path="/board/:canteenId" element={<TokenBoardPage />} />
              <Route
                path="/inventory"
                element={
                  <RequireRole allowed={["inventory_manager", "canteen_manager", "college_admin"]}>
                    <InventoryPage />
                  </RequireRole>
                }
              />
              <Route
                path="/admin"
                element={
                  <RequireRole allowed={["canteen_manager", "college_admin"]}>
                    <AdminConsolePage />
                  </RequireRole>
                }
              />
              <Route path="/kiosk" element={<KioskPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default App;
