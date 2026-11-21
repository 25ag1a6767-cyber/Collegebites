import React, { useEffect } from "react";
import { Tabs } from "expo-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMobileStore } from "../src/store/useMobileStore";

const qc = new QueryClient();

export default function RootLayout() {
  const hydrate = useMobileStore((s) => s.hydrate);
  useEffect(() => {
    hydrate();
  }, [hydrate]);

  return (
    <QueryClientProvider client={qc}>
      <Tabs
        screenOptions={{
          headerStyle: { backgroundColor: "#0f172a" },
          headerTintColor: "#ffffff",
          tabBarActiveTintColor: "#ea580c",
          tabBarInactiveTintColor: "#64748b",
        }}
      >
        <Tabs.Screen name="index" options={{ title: "Menu", tabBarLabel: "Menu" }} />
        <Tabs.Screen name="scan" options={{ title: "Scan QR", tabBarLabel: "Scan QR" }} />
        <Tabs.Screen name="checkout" options={{ title: "Checkout", tabBarLabel: "Cart" }} />
        <Tabs.Screen name="orders" options={{ title: "Orders", tabBarLabel: "Orders" }} />
        <Tabs.Screen name="profile" options={{ title: "Account", tabBarLabel: "Profile" }} />
        <Tabs.Screen name="order/[orderNumber]" options={{ href: null, title: "Order Token & Receipt" }} />
      </Tabs>
    </QueryClientProvider>
  );
}
