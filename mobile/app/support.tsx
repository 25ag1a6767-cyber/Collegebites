import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { authApi } from "../src/api/auth.api";
import { getMobileApiError, mobileApi } from "../src/api/client";
import { profileApi } from "../src/api/profile.api";
import { useMobileStore } from "../src/store/useMobileStore";

const CATEGORIES = [
  { key: "food_quality", label: "Food Quality" },
  { key: "missing_item", label: "Missing Item" },
  { key: "incorrect_order", label: "Wrong Order" },
  { key: "payment_issue", label: "Payment Issue" },
  { key: "order_issue", label: "Order Delay / Status" },
  { key: "app_help", label: "App / QR Help" },
  { key: "other", label: "Other" },
];

export default function SupportScreen() {
  const { order_id } = useLocalSearchParams<{ order_id?: string }>();
  const { user, selectedCanteenId } = useMobileStore();
  const [category, setCategory] = useState("food_quality");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [guestName, setGuestName] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [guestOtp, setGuestOtp] = useState("");
  const [guestOtpTok, setGuestOtpTok] = useState("");
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [guestTickets, setGuestTickets] = useState<any[]>([]);
  const [guestMessages, setGuestMessages] = useState<any[]>([]);
  const [statusMsg, setStatusMsg] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [replyText, setReplyText] = useState("");
  const [busy, setBusy] = useState(false);

  const { data: tickets = [], refetch } = useQuery<any[]>({
    queryKey: ["m-my-tickets"],
    enabled: Boolean(user),
    queryFn: profileApi.listMyTickets,
  });

  const { data: messages = [], refetch: refetchMessages } = useQuery<any[]>({
    queryKey: ["m-ticket-msgs", selectedId],
    enabled: Boolean(selectedId && user),
    queryFn: async () => (await mobileApi.get(`/support/tickets/${selectedId}/messages`)).data,
  });

  const loadGuestThread = async (ticketId: string, tokenOverride?: string) => {
    const tok = tokenOverride || guestOtpTok;
    if (!tok || !guestPhone.trim()) return;
    try {
      const res = await mobileApi.post(`/support/tickets/${ticketId}/guest-thread`, {
        guest_phone: guestPhone.trim(),
        otp_verification_token: tok,
      });
      setSelectedId(ticketId);
      setGuestMessages(res.data.messages || []);
    } catch (e: unknown) {
      setStatusMsg(getMobileApiError(e, "Could not load conversation"));
    }
  };

  const submitTicket = async () => {
    setStatusMsg("");
    setBusy(true);
    try {
      const data = await profileApi.submitTicket({
        order_id: order_id || null,
        canteen_id: selectedCanteenId || null,
        category,
        subject,
        description,
        guest_name: !user ? guestName : null,
        guest_phone: !user ? guestPhone : null,
      });
      setSubject("");
      setDescription("");
      setStatusMsg(`Ticket ${data.ticket_number} submitted.`);
      if (user) refetch();
      else setGuestTickets((prev) => [data, ...prev]);
    } catch (e: unknown) {
      setStatusMsg(getMobileApiError(e, "Could not submit ticket"));
    } finally {
      setBusy(false);
    }
  };

  const sendReply = async () => {
    if (!selectedId || !replyText.trim()) return;
    setBusy(true);
    try {
      if (user) {
        await mobileApi.post(`/support/tickets/${selectedId}/messages`, { message: replyText.trim() });
        setReplyText("");
        refetchMessages();
      } else if (guestOtpTok) {
        await mobileApi.post(`/support/tickets/${selectedId}/guest-messages`, {
          guest_phone: guestPhone.trim(),
          otp_verification_token: guestOtpTok,
          message: replyText.trim(),
        });
        setReplyText("");
        await loadGuestThread(selectedId);
      }
    } catch (e: unknown) {
      setStatusMsg(getMobileApiError(e, "Could not send message"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ gap: 14, paddingBottom: 40 }}>
      <Text style={styles.title}>Customer Support &amp; Complaints</Text>
      <Text style={styles.note}>Note: CollegeBites does not issue in-app refunds.</Text>

      <View style={styles.card}>
        <Text style={styles.secTitle}>Submit New Issue</Text>
        <View style={styles.catRow}>
          {CATEGORIES.map((c) => (
            <Pressable
              key={c.key}
              onPress={() => setCategory(c.key)}
              style={[styles.catPill, category === c.key && styles.catPillActive]}
            >
              <Text style={[styles.catTxt, category === c.key && { color: "#fff" }]}>{c.label}</Text>
            </Pressable>
          ))}
        </View>
        {!user && (
          <>
            <TextInput style={styles.input} value={guestName} onChangeText={setGuestName} placeholder="Your Name" />
            <TextInput style={styles.input} value={guestPhone} onChangeText={setGuestPhone} placeholder="Mobile Number" />
          </>
        )}
        <TextInput style={styles.input} value={subject} onChangeText={setSubject} placeholder="Subject" />
        <TextInput
          style={[styles.input, { minHeight: 80, textAlignVertical: "top" }]}
          multiline
          value={description}
          onChangeText={setDescription}
          placeholder="Describe what happened..."
        />
        {Boolean(statusMsg) && <Text style={{ color: "#76010d", fontWeight: "700", fontSize: 12 }}>{statusMsg}</Text>}
        <Pressable disabled={busy} onPress={submitTicket} style={styles.btn}>
          <Text style={styles.btnTxt}>{busy ? "Submitting..." : "Submit Ticket"}</Text>
        </Pressable>
      </View>

      {!user && (
        <View style={styles.card}>
          <Text style={styles.secTitle}>Guest Ticket OTP Lookup</Text>
          <View style={{ flexDirection: "row", gap: 6 }}>
            <TextInput style={[styles.input, { flex: 1 }]} value={guestPhone} onChangeText={setGuestPhone} placeholder="Guest Phone" />
            <Pressable
              disabled={busy || !guestPhone.trim()}
              onPress={async () => {
                setBusy(true);
                try {
                  const r = await authApi.requestOtp({ target: guestPhone.trim(), purpose: "guest_checkout" });
                  setDevOtp(r.dev_otp || null);
                } catch (e: unknown) {
                  setStatusMsg(getMobileApiError(e));
                } finally {
                  setBusy(false);
                }
              }}
              style={[styles.btn, { paddingHorizontal: 12 }]}
            >
              <Text style={styles.btnTxt}>Send OTP</Text>
            </Pressable>
          </View>
          {devOtp && <Text style={{ fontSize: 11, color: "#b45309" }}>Dev OTP: {devOtp}</Text>}
          <View style={{ flexDirection: "row", gap: 6 }}>
            <TextInput style={[styles.input, { flex: 1 }]} value={guestOtp} onChangeText={setGuestOtp} placeholder="6-digit OTP" maxLength={6} />
            <Pressable
              disabled={busy || guestOtp.trim().length < 6}
              onPress={async () => {
                setBusy(true);
                try {
                  const ver = await authApi.verifyOtp({
                    target: guestPhone.trim(),
                    purpose: "guest_checkout",
                    code: guestOtp.trim(),
                  });
                  const tok = ver.verification_token;
                  setGuestOtpTok(tok);
                  const rows = await mobileApi.post("/support/tickets/guest/lookup", {
                    guest_phone: guestPhone.trim(),
                    otp_verification_token: tok,
                  });
                  setGuestTickets(rows.data || []);
                } catch (e: unknown) {
                  setStatusMsg(getMobileApiError(e));
                } finally {
                  setBusy(false);
                }
              }}
              style={[styles.btn, { paddingHorizontal: 12, backgroundColor: "#0f172a" }]}
            >
              <Text style={styles.btnTxt}>Verify</Text>
            </Pressable>
          </View>
        </View>
      )}

      {(user || guestTickets.length > 0) && (
        <View style={styles.card}>
          <Text style={styles.secTitle}>Your Tickets ({(user ? tickets : guestTickets).length})</Text>
          {(user ? tickets : guestTickets).map((t) => (
            <Pressable
              key={t.id}
              onPress={() => (user ? setSelectedId(t.id) : void loadGuestThread(t.id))}
              style={[styles.ticketRow, selectedId === t.id && { borderColor: "#76010d", backgroundColor: "#fdf8f0" }]}
            >
              <Text style={{ fontWeight: "800", fontSize: 13 }}>{t.ticket_number} • {t.subject}</Text>
              <Text style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                {t.category} • {t.status}
                {t.resolution_minutes != null ? ` • Resolved in ${t.resolution_minutes}m` : ""}
              </Text>
            </Pressable>
          ))}
          {selectedId && (
            <View style={{ gap: 8, marginTop: 8 }}>
              {(user ? messages : guestMessages).map((m) => (
                <View key={m.id} style={styles.msgBubble}>
                  <Text style={{ fontWeight: "700", fontSize: 11, color: "#475569" }}>{m.sender_role}</Text>
                  <Text style={{ fontSize: 12 }}>{m.message}</Text>
                </View>
              ))}
              {(user || guestOtpTok) && (
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <TextInput style={[styles.input, { flex: 1 }]} value={replyText} onChangeText={setReplyText} placeholder="Write reply..." />
                  <Pressable disabled={busy} onPress={sendReply} style={[styles.btn, { paddingHorizontal: 14 }]}>
                    <Text style={styles.btnTxt}>Send</Text>
                  </Pressable>
                </View>
              )}
            </View>
          )}
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  title: { fontSize: 20, fontWeight: "800", color: "#0f172a" },
  note: { fontSize: 12, color: "#64748b" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 14, gap: 10, borderWidth: 1, borderColor: "#e2e8f0" },
  secTitle: { fontWeight: "800", fontSize: 15, color: "#0f172a" },
  catRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  catPill: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 16, backgroundColor: "#f1f5f9" },
  catPillActive: { backgroundColor: "#0f172a" },
  catTxt: { fontSize: 11, fontWeight: "700", color: "#334155" },
  input: { backgroundColor: "#f8fafc", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  btn: { backgroundColor: "#76010d", borderRadius: 10, paddingVertical: 12, alignItems: "center", justifyContent: "center" },
  btnTxt: { color: "#fff", fontWeight: "800" },
  ticketRow: { borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 10, padding: 10 },
  msgBubble: { backgroundColor: "#f1f5f9", borderRadius: 8, padding: 8 },
});
