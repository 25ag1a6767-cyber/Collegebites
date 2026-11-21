import React, { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View, ActivityIndicator } from "react-native";
import { Tabs } from "expo-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Ionicons } from "@expo/vector-icons";
import { useMobileStore } from "../src/store/useMobileStore";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 3_000,
    },
  },
});

const ONBOARDING_SLIDES = [
  {
    icon: "restaurant-outline" as const,
    title: "Discover Campus Canteens",
    body: "Switch seamlessly across Main Canteen, Snacks & Bakery, and Juice Bar with real-time wait times and crowd levels.",
  },
  {
    icon: "options-outline" as const,
    title: "Browse & Customize Food",
    body: "Filter veg/non-veg dishes, pick variants, add toppings, set spice or sugar levels, and add kitchen instructions.",
  },
  {
    icon: "card-outline" as const,
    title: "Pay Online Instantly",
    body: "Checkout as a student or OTP-verified guest using Razorpay or Stripe — backed by server verification.",
  },
  {
    icon: "qr-code-outline" as const,
    title: "Live Tracking & QR Token",
    body: "Receive your unique human-readable pickup token, signed QR pass, complete receipt, and live kitchen updates.",
  },
];

function OnboardingOverlay({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const slide = ONBOARDING_SLIDES[step];
  const isLast = step === ONBOARDING_SLIDES.length - 1;

  return (
    <View style={styles.onboardRoot}>
      <View style={styles.onboardTop}>
        <View style={styles.brandRow}>
          <View style={styles.logoBadge}>
            <Text style={styles.logoText}>CB</Text>
          </View>
          <Text style={styles.brandName}>CollegeBites</Text>
        </View>
        <Pressable onPress={onDone} style={styles.skipBtn}>
          <Text style={styles.skipText}>Skip</Text>
        </Pressable>
      </View>

      <View style={styles.slideCard}>
        <View style={styles.iconCircle}>
          <Ionicons name={slide.icon} size={46} color="#ea580c" />
        </View>
        <Text style={styles.slideTitle}>{slide.title}</Text>
        <Text style={styles.slideBody}>{slide.body}</Text>

        <View style={styles.dots}>
          {ONBOARDING_SLIDES.map((_, idx) => (
            <View key={idx} style={[styles.dot, idx === step && styles.dotActive]} />
          ))}
        </View>
      </View>

      <View style={styles.onboardFooter}>
        {step > 0 ? (
          <Pressable onPress={() => setStep((s) => s - 1)} style={styles.backBtn}>
            <Text style={styles.backTxt}>Back</Text>
          </Pressable>
        ) : (
          <View />
        )}
        <Pressable
          onPress={() => (isLast ? onDone() : setStep((s) => s + 1))}
          style={styles.nextBtn}
        >
          <Text style={styles.nextTxt}>{isLast ? "Get Started →" : "Next →"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function RootLayout() {
  const hydrate = useMobileStore((s) => s.hydrate);
  const hydrated = useMobileStore((s) => s.hydrated);
  const onboardingSeen = useMobileStore((s) => s.onboardingSeen);
  const markOnboardingSeen = useMobileStore((s) => s.markOnboardingSeen);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  if (!hydrated) {
    return (
      <View style={styles.splashRoot}>
        <View style={styles.splashLogo}>
          <Text style={styles.splashLogoTxt}>CB</Text>
        </View>
        <Text style={styles.splashTitle}>CollegeBites</Text>
        <Text style={styles.splashSub}>Smart Campus Canteen Ordering &amp; Live QR Tokens</Text>
        <ActivityIndicator size="large" color="#ffffff" style={{ marginTop: 22 }} />
      </View>
    );
  }

  if (!onboardingSeen) {
    return <OnboardingOverlay onDone={() => void markOnboardingSeen()} />;
  }

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
        <Tabs.Screen
          name="index"
          options={{
            title: "CollegeBites",
            tabBarLabel: "Home",
            tabBarIcon: ({ color, size }) => <Ionicons name="restaurant-outline" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="scan"
          options={{
            title: "Scan QR",
            tabBarLabel: "Scan QR",
            tabBarIcon: ({ color, size }) => <Ionicons name="qr-code-outline" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="checkout"
          options={{
            title: "Cart & Checkout",
            tabBarLabel: "Cart",
            tabBarIcon: ({ color, size }) => <Ionicons name="cart-outline" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="orders"
          options={{
            title: "Orders & Tokens",
            tabBarLabel: "Orders",
            tabBarIcon: ({ color, size }) => <Ionicons name="receipt-outline" size={size} color={color} />,
          }}
        />
        <Tabs.Screen
          name="profile"
          options={{
            title: "Account & Settings",
            tabBarLabel: "Profile",
            tabBarIcon: ({ color, size }) => <Ionicons name="person-outline" size={size} color={color} />,
          }}
        />
        <Tabs.Screen name="board" options={{ href: null, title: "Live Token Board" }} />
        <Tabs.Screen name="support" options={{ href: null, title: "Customer Support" }} />
        <Tabs.Screen name="order/[orderNumber]" options={{ href: null, title: "Order Token & Receipt" }} />
        <Tabs.Screen name="scan/[code]" options={{ href: null, title: "Location QR" }} />
      </Tabs>
    </QueryClientProvider>
  );
}

const styles = StyleSheet.create({
  splashRoot: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "#ea580c", padding: 24 },
  splashLogo: {
    width: 82,
    height: 82,
    borderRadius: 24,
    backgroundColor: "#ffffff",
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 14,
  },
  splashLogoTxt: { color: "#ea580c", fontSize: 32, fontWeight: "900" },
  splashTitle: { color: "#ffffff", fontSize: 28, fontWeight: "900", letterSpacing: 0.5 },
  splashSub: { color: "#ffedd5", fontSize: 13, fontWeight: "600", marginTop: 6, textAlign: "center" },
  onboardRoot: { flex: 1, backgroundColor: "#f8fafc", padding: 22, justifyContent: "space-between" },
  onboardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingTop: 24 },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  logoBadge: { width: 38, height: 38, borderRadius: 11, backgroundColor: "#ea580c", alignItems: "center", justifyContent: "center" },
  logoText: { color: "#fff", fontWeight: "900", fontSize: 15 },
  brandName: { fontSize: 18, fontWeight: "900", color: "#0f172a" },
  skipBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20, backgroundColor: "#e2e8f0" },
  skipText: { fontSize: 12, fontWeight: "800", color: "#334155" },
  slideCard: { backgroundColor: "#fff", borderRadius: 24, padding: 28, alignItems: "center", gap: 14, borderWidth: 1, borderColor: "#e2e8f0" },
  iconCircle: { width: 88, height: 88, borderRadius: 44, backgroundColor: "#fff7ed", alignItems: "center", justifyContent: "center" },
  slideTitle: { fontSize: 22, fontWeight: "900", color: "#0f172a", textAlign: "center" },
  slideBody: { fontSize: 14, color: "#475569", textAlign: "center", lineHeight: 21 },
  dots: { flexDirection: "row", gap: 6, marginTop: 8 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#cbd5e1" },
  dotActive: { width: 22, backgroundColor: "#ea580c" },
  onboardFooter: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingBottom: 16 },
  backBtn: { paddingHorizontal: 18, paddingVertical: 12, borderRadius: 12, backgroundColor: "#e2e8f0" },
  backTxt: { fontWeight: "800", color: "#0f172a" },
  nextBtn: { paddingHorizontal: 24, paddingVertical: 13, borderRadius: 12, backgroundColor: "#ea580c" },
  nextTxt: { fontWeight: "800", color: "#fff", fontSize: 14 },
});
