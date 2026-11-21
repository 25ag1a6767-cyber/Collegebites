import React, { useState } from "react";
import {
  FlatList,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";

export default function MenuScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, selectedCanteenId, setCanteen } = useMobileStore();
  const [search, setSearch] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [vegFilter, setVegFilter] = useState<"all" | "veg" | "nonveg">("all");
  const [tagFilter, setTagFilter] = useState<"all" | "featured" | "popular" | "special">("all");
  const [sortBy, setSortBy] = useState<"popularity" | "price_asc" | "price_desc">("popularity");

  // Customization & Detail Modal State
  const [activeItem, setActiveItem] = useState<any | null>(null);
  const [selVariantId, setSelVariantId] = useState("");
  const [selSpice, setSelSpice] = useState("");
  const [selSugar, setSelSugar] = useState("");
  const [selRemoved, setSelRemoved] = useState<string[]>([]);
  const [selAddons, setSelAddons] = useState<Record<string, number>>({});
  const [qty, setQty] = useState(1);
  const [instructions, setInstructions] = useState("");
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewComment, setReviewComment] = useState("");
  const [modalMsg, setModalMsg] = useState("");

  const { data: canteens = [] } = useQuery<any[]>({
    queryKey: ["m-canteens"],
    queryFn: async () => (await mobileApi.get("/canteens")).data,
  });
  const activeCanteen = canteens.find((c) => c.id === selectedCanteenId) || canteens[0];

  const { data: categories = [] } = useQuery<any[]>({
    queryKey: ["m-categories", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => (await mobileApi.get(`/menus/canteens/${activeCanteen.id}/categories`)).data,
  });

  const { data: announcements = [] } = useQuery<any[]>({
    queryKey: ["m-announcements"],
    queryFn: async () => (await mobileApi.get("/notifications/announcements")).data,
  });

  const { data: profile } = useQuery<any>({
    queryKey: ["m-profile"],
    enabled: Boolean(user),
    queryFn: async () => (await mobileApi.get("/customers/profile")).data,
  });

  const { data: items = [] } = useQuery<any[]>({
    queryKey: ["m-items", activeCanteen?.id, search, selectedCategoryId, vegFilter, tagFilter, sortBy],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (search.trim()) params.set("q", search.trim());
      if (selectedCategoryId) params.set("category_id", selectedCategoryId);
      if (vegFilter === "veg") params.set("is_veg", "true");
      if (vegFilter === "nonveg") params.set("is_veg", "false");
      if (tagFilter === "featured") params.set("featured", "true");
      if (tagFilter === "popular") params.set("popular", "true");
      if (tagFilter === "special") params.set("todays_special", "true");
      params.set("sort_by", sortBy);
      return (await mobileApi.get(`/menus/canteens/${activeCanteen.id}/items?${params.toString()}`)).data;
    },
  });

  const { data: cart } = useQuery<any>({
    queryKey: ["m-cart", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => (await mobileApi.get(`/carts?canteen_id=${activeCanteen.id}`)).data,
  });

  const { data: itemReviews = [] } = useQuery<any[]>({
    queryKey: ["m-item-reviews", activeItem?.id],
    enabled: Boolean(activeItem?.id),
    queryFn: async () => (await mobileApi.get(`/support/items/${activeItem.id}/reviews`)).data,
  });

  const openModal = (item: any) => {
    setActiveItem(item);
    const defVar = item.variants?.find((v: any) => v.is_default) || item.variants?.[0];
    setSelVariantId(defVar?.id || "");
    setSelSpice(item.spice_levels?.[0] || "");
    setSelSugar(item.sugar_levels?.[0] || "");
    setSelRemoved([]);
    setSelAddons({});
    setQty(1);
    setInstructions("");
    setModalMsg("");
  };

  const addMut = useMutation({
    mutationFn: async () => {
      if (!activeItem || !activeCanteen) return;
      const addons = Object.entries(selAddons)
        .filter(([, q]) => q > 0)
        .map(([addon_id, quantity]) => ({ addon_id, quantity }));
      return (
        await mobileApi.post("/carts/items", {
          canteen_id: activeCanteen.id,
          food_item_id: activeItem.id,
          variant_id: selVariantId || null,
          quantity: qty,
          spice_level: selSpice || null,
          sugar_level: selSugar || null,
          removed_ingredients: selRemoved,
          addons,
          special_instructions: instructions.trim() || null,
        })
      ).data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["m-cart", activeCanteen?.id] });
      setActiveItem(null);
    },
    onError: (e: any) => setModalMsg(e?.response?.data?.detail || "Could not add item"),
  });

  const toggleFav = async (foodId: string) => {
    if (!user) return;
    const isFav = profile?.favourite_item_ids?.includes(foodId);
    if (isFav) await mobileApi.delete(`/customers/favourites/${foodId}`);
    else await mobileApi.post(`/customers/favourites/${foodId}`);
    qc.invalidateQueries({ queryKey: ["m-profile"] });
  };

  const submitReview = async () => {
    if (!activeItem) return;
    try {
      await mobileApi.post("/support/reviews", {
        food_item_id: activeItem.id,
        rating: reviewRating,
        comment: reviewComment.trim() || null,
      });
      setReviewComment("");
      qc.invalidateQueries({ queryKey: ["m-item-reviews", activeItem.id] });
      qc.invalidateQueries({ queryKey: ["m-items"] });
      setModalMsg("Review submitted!");
    } catch (e: any) {
      setModalMsg(e?.response?.data?.detail || "Sign in to submit review");
    }
  };

  const modalPrice = (() => {
    if (!activeItem) return 0;
    const v = activeItem.variants?.find((x: any) => x.id === selVariantId);
    const base = v?.absolute_price
      ? Number(v.absolute_price)
      : Number(activeItem.base_price) + Number(v?.price_delta || 0);
    const addonSum = Object.entries(selAddons).reduce((acc, [id, cnt]) => {
      const ad = activeItem.addons?.find((a: any) => a.id === id);
      return acc + (ad ? Number(ad.price) * cnt : 0);
    }, 0);
    return (base + addonSum) * qty;
  })();

  return (
    <View style={styles.container}>
      {/* Announcements + Live Board link */}
      <View style={styles.topRow}>
        <Text style={styles.brandSub} numberOfLines={1}>
          {announcements[0]?.title || (activeCanteen?.is_open_now ? "Canteen Open • Ordering Live" : "Canteen Closed")}
        </Text>
        <Pressable onPress={() => router.push("/board")} style={styles.boardChip}>
          <Text style={styles.boardChipTxt}>Live Board →</Text>
        </Pressable>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.canteenBar}>
        {canteens.map((c) => {
          const active = c.id === activeCanteen?.id;
          return (
            <Pressable
              key={c.id}
              onPress={() => {
                setCanteen(c.id);
                setSelectedCategoryId("");
              }}
              style={[styles.canteenPill, active && styles.canteenPillActive]}
            >
              <Text style={[styles.canteenTitle, active && { color: "#fff" }]}>{c.name}</Text>
              <Text style={[styles.canteenSub, active && { color: "#fed7aa" }]}>
                {c.crowd_level} • ~{c.estimated_wait_minutes}m
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>

      <View style={styles.searchRow}>
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder="Search biryani, dosa, coffee..."
        />
        <Pressable
          onPress={() => setVegFilter((v) => (v === "all" ? "veg" : v === "veg" ? "nonveg" : "all"))}
          style={[
            styles.vegBtn,
            vegFilter === "veg" && { backgroundColor: "#059669", borderColor: "#059669" },
            vegFilter === "nonveg" && { backgroundColor: "#dc2626", borderColor: "#dc2626" },
          ]}
        >
          <Text style={[styles.vegText, vegFilter !== "all" && { color: "#fff" }]}>
            {vegFilter === "all" ? "All" : vegFilter === "veg" ? "Veg" : "Non-Veg"}
          </Text>
        </Pressable>
        <Pressable
          onPress={() =>
            setSortBy((s) => (s === "popularity" ? "price_asc" : s === "price_asc" ? "price_desc" : "popularity"))
          }
          style={styles.vegBtn}
        >
          <Text style={styles.vegText}>
            {sortBy === "popularity" ? "Popular" : sortBy === "price_asc" ? "₹ Low" : "₹ High"}
          </Text>
        </Pressable>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipBar}>
        <Pressable
          onPress={() => setSelectedCategoryId("")}
          style={[styles.chip, selectedCategoryId === "" && styles.chipActive]}
        >
          <Text style={[styles.chipTxt, selectedCategoryId === "" && { color: "#fff" }]}>All</Text>
        </Pressable>
        {categories.map((cat) => (
          <Pressable
            key={cat.id}
            onPress={() => setSelectedCategoryId(cat.id)}
            style={[styles.chip, selectedCategoryId === cat.id && styles.chipActive]}
          >
            <Text style={[styles.chipTxt, selectedCategoryId === cat.id && { color: "#fff" }]}>{cat.name}</Text>
          </Pressable>
        ))}
        {(["featured", "popular", "special"] as const).map((tg) => (
          <Pressable
            key={tg}
            onPress={() => setTagFilter((cur) => (cur === tg ? "all" : tg))}
            style={[styles.chip, tagFilter === tg && { backgroundColor: "#ea580c", borderColor: "#ea580c" }]}
          >
            <Text style={[styles.chipTxt, tagFilter === tg && { color: "#fff" }]}>
              {tg === "special" ? "Special" : tg}
            </Text>
          </Pressable>
        ))}
      </ScrollView>

      <FlatList
        data={items}
        keyExtractor={(item) => item.id}
        contentContainerStyle={{ paddingBottom: 95, gap: 10 }}
        renderItem={({ item }) => {
          const unavailable = !item.is_available || item.insufficient_ingredients || !activeCanteen?.is_open_now;
          const isFav = profile?.favourite_item_ids?.includes(item.id);
          return (
            <Pressable onPress={() => openModal(item)} style={styles.card}>
              <Image
                source={{ uri: item.images?.[0]?.image_url || "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=400" }}
                style={styles.thumb}
              />
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                  <Text style={styles.itemTitle} numberOfLines={1}>
                    {item.is_veg ? "🟢" : "🔴"} {item.name}
                  </Text>
                  {user && (
                    <Pressable onPress={() => toggleFav(item.id)}>
                      <Text style={{ fontSize: 16 }}>{isFav ? "❤️" : "🤍"}</Text>
                    </Pressable>
                  )}
                </View>
                <Text style={styles.itemDesc} numberOfLines={2}>
                  {item.description}
                </Text>
                <Text style={styles.itemMeta}>
                  ₹{item.base_price} • {item.prep_time_minutes}m • ★ {item.average_rating}
                </Text>
              </View>
              <Pressable
                disabled={unavailable}
                onPress={() => openModal(item)}
                style={[styles.addBtn, unavailable && { backgroundColor: "#cbd5e1" }]}
              >
                <Text style={styles.addBtnText}>{unavailable ? "Unavail" : "Customize"}</Text>
              </Pressable>
            </Pressable>
          );
        }}
      />

      {cart && cart.items?.length > 0 && (
        <Pressable onPress={() => router.push("/checkout")} style={styles.cartBar}>
          <Text style={styles.cartBarText}>
            {cart.items.reduce((s: number, i: any) => s + i.quantity, 0)} items • ₹{cart.total_amount}
          </Text>
          <Text style={styles.cartBarText}>Checkout →</Text>
        </Pressable>
      )}

      {/* Full Food Customization & Detail Modal */}
      <Modal visible={Boolean(activeItem)} animationType="slide" onRequestClose={() => setActiveItem(null)}>
        {activeItem && (
          <ScrollView style={styles.modalWrap} contentContainerStyle={{ gap: 14, paddingBottom: 40 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={{ fontSize: 20, fontWeight: "900", color: "#0f172a", flex: 1 }}>{activeItem.name}</Text>
              <Pressable onPress={() => setActiveItem(null)} style={styles.closeBtn}>
                <Text style={{ fontWeight: "800" }}>Close</Text>
              </Pressable>
            </View>

            <Image
              source={{ uri: activeItem.images?.[0]?.image_url || "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=600" }}
              style={styles.heroImg}
            />
            <Text style={{ fontSize: 13, color: "#475569" }}>{activeItem.description}</Text>
            {Boolean(activeItem.ingredients_text) && (
              <Text style={{ fontSize: 12, color: "#64748b" }}>Ingredients: {activeItem.ingredients_text}</Text>
            )}
            {activeItem.allergens?.length > 0 && (
              <Text style={{ fontSize: 12, color: "#b45309", fontWeight: "700" }}>
                Allergens: {activeItem.allergens.map((a: any) => a.name).join(", ")}
              </Text>
            )}

            {activeItem.variants?.length > 0 && (
              <View style={styles.secBox}>
                <Text style={styles.secTitle}>Portion / Variant</Text>
                {activeItem.variants.map((v: any) => {
                  const p = v.absolute_price
                    ? Number(v.absolute_price)
                    : Number(activeItem.base_price) + Number(v.price_delta || 0);
                  const active = selVariantId === v.id;
                  return (
                    <Pressable
                      key={v.id}
                      onPress={() => setSelVariantId(v.id)}
                      style={[styles.optRow, active && styles.optRowActive]}
                    >
                      <Text style={{ fontWeight: "700" }}>{v.name}</Text>
                      <Text style={{ fontWeight: "800", color: "#ea580c" }}>₹{p.toFixed(2)}</Text>
                    </Pressable>
                  );
                })}
              </View>
            )}

            {activeItem.addons?.length > 0 && (
              <View style={styles.secBox}>
                <Text style={styles.secTitle}>Add-ons & Extra Toppings</Text>
                {activeItem.addons.map((ad: any) => {
                  const cnt = selAddons[ad.id] || 0;
                  return (
                    <View key={ad.id} style={styles.optRow}>
                      <Text style={{ fontWeight: "600" }}>
                        {ad.name} (+₹{ad.price})
                      </Text>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                        <Pressable
                          onPress={() => setSelAddons((p) => ({ ...p, [ad.id]: Math.max(0, cnt - 1) }))}
                          style={styles.qtyBtn}
                        >
                          <Text style={{ fontWeight: "800" }}>-</Text>
                        </Pressable>
                        <Text style={{ fontWeight: "800" }}>{cnt}</Text>
                        <Pressable
                          onPress={() => setSelAddons((p) => ({ ...p, [ad.id]: cnt + 1 }))}
                          style={styles.qtyBtn}
                        >
                          <Text style={{ fontWeight: "800" }}>+</Text>
                        </Pressable>
                      </View>
                    </View>
                  );
                })}
              </View>
            )}

            {activeItem.spice_levels?.length > 0 && (
              <View style={styles.secBox}>
                <Text style={styles.secTitle}>Spice Level</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                  {activeItem.spice_levels.map((sp: string) => (
                    <Pressable
                      key={sp}
                      onPress={() => setSelSpice(sp)}
                      style={[styles.chip, selSpice === sp && styles.chipActive]}
                    >
                      <Text style={[styles.chipTxt, selSpice === sp && { color: "#fff" }]}>{sp}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )}

            {activeItem.sugar_levels?.length > 0 && (
              <View style={styles.secBox}>
                <Text style={styles.secTitle}>Sugar Level</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                  {activeItem.sugar_levels.map((sg: string) => (
                    <Pressable
                      key={sg}
                      onPress={() => setSelSugar(sg)}
                      style={[styles.chip, selSugar === sg && styles.chipActive]}
                    >
                      <Text style={[styles.chipTxt, selSugar === sg && { color: "#fff" }]}>{sg}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )}

            {activeItem.removable_ingredients?.length > 0 && (
              <View style={styles.secBox}>
                <Text style={styles.secTitle}>Remove Ingredients</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                  {activeItem.removable_ingredients.map((ri: string) => {
                    const checked = selRemoved.includes(ri);
                    return (
                      <Pressable
                        key={ri}
                        onPress={() =>
                          setSelRemoved((p) => (checked ? p.filter((x) => x !== ri) : [...p, ri]))
                        }
                        style={[styles.chip, checked && { backgroundColor: "#dc2626", borderColor: "#dc2626" }]}
                      >
                        <Text style={[styles.chipTxt, checked && { color: "#fff" }]}>No {ri}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            )}

            <TextInput
              style={styles.searchInput}
              value={instructions}
              onChangeText={setInstructions}
              placeholder="Special kitchen instructions..."
            />

            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
                <Pressable onPress={() => setQty((q) => Math.max(1, q - 1))} style={styles.qtyBtn}>
                  <Text style={{ fontWeight: "800" }}>-</Text>
                </Pressable>
                <Text style={{ fontSize: 16, fontWeight: "900" }}>{qty}</Text>
                <Pressable onPress={() => setQty((q) => q + 1)} style={styles.qtyBtn}>
                  <Text style={{ fontWeight: "800" }}>+</Text>
                </Pressable>
              </View>
              <Pressable onPress={() => addMut.mutate()} style={[styles.addBtn, { flex: 1, alignItems: "center", paddingVertical: 14 }]}>
                <Text style={styles.addBtnText}>Add to Cart • ₹{modalPrice.toFixed(2)}</Text>
              </Pressable>
            </View>

            {Boolean(modalMsg) && <Text style={{ color: "#ea580c", fontWeight: "700" }}>{modalMsg}</Text>}

            {/* Item Reviews */}
            <View style={styles.secBox}>
              <Text style={styles.secTitle}>Reviews ({itemReviews.length})</Text>
              {itemReviews.slice(0, 4).map((r: any) => (
                <Text key={r.id} style={{ fontSize: 12, color: "#475569" }}>
                  ★ {r.rating} — {r.comment || "Good"}
                </Text>
              ))}
              {user && (
                <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
                  <Pressable
                    onPress={() => setReviewRating((n) => (n >= 5 ? 1 : n + 1))}
                    style={styles.qtyBtn}
                  >
                    <Text style={{ fontWeight: "800" }}>{reviewRating}★</Text>
                  </Pressable>
                  <TextInput
                    style={[styles.searchInput, { flex: 1 }]}
                    value={reviewComment}
                    onChangeText={setReviewComment}
                    placeholder="Rate this dish..."
                  />
                  <Pressable onPress={submitReview} style={styles.addBtn}>
                    <Text style={styles.addBtnText}>Post</Text>
                  </Pressable>
                </View>
              )}
            </View>
          </ScrollView>
        )}
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 12 },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  brandSub: { flex: 1, fontSize: 12, fontWeight: "700", color: "#475569", marginRight: 8 },
  boardChip: { backgroundColor: "#0f172a", paddingHorizontal: 10, paddingVertical: 5, borderRadius: 12 },
  boardChipTxt: { color: "#fff", fontSize: 11, fontWeight: "700" },
  canteenBar: { maxHeight: 62, marginBottom: 8 },
  canteenPill: { backgroundColor: "#fff", borderRadius: 12, padding: 10, marginRight: 8, borderWidth: 1, borderColor: "#e2e8f0" },
  canteenPillActive: { backgroundColor: "#0f172a", borderColor: "#0f172a" },
  canteenTitle: { fontWeight: "700", fontSize: 13, color: "#0f172a" },
  canteenSub: { fontSize: 11, color: "#64748b", marginTop: 2 },
  searchRow: { flexDirection: "row", gap: 6, marginBottom: 8 },
  searchInput: { flex: 1, backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#cbd5e1", paddingHorizontal: 12, paddingVertical: 8 },
  vegBtn: { justifyContent: "center", paddingHorizontal: 11, borderRadius: 12, borderWidth: 1, borderColor: "#cbd5e1", backgroundColor: "#fff" },
  vegText: { fontWeight: "700", fontSize: 12, color: "#0f172a" },
  chipBar: { maxHeight: 38, marginBottom: 8 },
  chip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 18, backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd5e1", marginRight: 6 },
  chipActive: { backgroundColor: "#0f172a", borderColor: "#0f172a" },
  chipTxt: { fontSize: 12, fontWeight: "700", color: "#334155" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 12, flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderColor: "#e2e8f0" },
  thumb: { width: 64, height: 64, borderRadius: 10, backgroundColor: "#e2e8f0" },
  itemTitle: { fontWeight: "800", fontSize: 14, color: "#0f172a", flex: 1 },
  itemDesc: { fontSize: 11, color: "#64748b", marginTop: 2 },
  itemMeta: { fontSize: 12, fontWeight: "700", color: "#ea580c", marginTop: 4 },
  addBtn: { backgroundColor: "#ea580c", borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  addBtnText: { color: "#fff", fontWeight: "700", fontSize: 12 },
  cartBar: { position: "absolute", bottom: 14, left: 14, right: 14, backgroundColor: "#0f172a", borderRadius: 14, padding: 14, flexDirection: "row", justifyContent: "space-between" },
  cartBarText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  modalWrap: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  closeBtn: { backgroundColor: "#e2e8f0", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8 },
  heroImg: { width: "100%", height: 180, borderRadius: 14, backgroundColor: "#e2e8f0" },
  secBox: { backgroundColor: "#fff", borderRadius: 12, padding: 12, gap: 8, borderWidth: 1, borderColor: "#e2e8f0" },
  secTitle: { fontWeight: "800", fontSize: 13, color: "#0f172a" },
  optRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 10, borderRadius: 10, borderWidth: 1, borderColor: "#e2e8f0" },
  optRowActive: { borderColor: "#ea580c", backgroundColor: "#fff7ed" },
  qtyBtn: { width: 32, height: 32, borderRadius: 8, backgroundColor: "#e2e8f0", alignItems: "center", justifyContent: "center" },
});
