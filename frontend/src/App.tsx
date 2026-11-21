import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Navbar } from "./components/layout/Navbar";
import { ToastProvider } from "./components/ui/Primitives";
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
              <Route path="/kitchen" element={<KitchenDisplayPage />} />
              <Route path="/cashier" element={<CashierPOSPage />} />
              <Route path="/pickup" element={<PickupScannerPage />} />
              <Route path="/pickup/verify" element={<PickupScannerPage />} />
              <Route path="/board" element={<TokenBoardPage />} />
              <Route path="/board/:canteenId" element={<TokenBoardPage />} />
              <Route path="/inventory" element={<InventoryPage />} />
              <Route path="/admin" element={<AdminConsolePage />} />
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
