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
import { canteensApi } from "../src/api/canteens.api";
import { cartApi } from "../src/api/cart.api";
import { getMobileApiError } from "../src/api/client";
import { menuApi } from "../src/api/menu.api";
import { ordersApi } from "../src/api/orders.api";
import { profileApi } from "../src/api/profile.api";
import { useMobileStore } from "../src/store/useMobileStore";
import { BrandLogo } from "../src/components/BrandLogo";

const ACTIVE_STATUSES = new Set(["PAYMENT_PENDING", "PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING", "READY"]);

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

  const { data: college } = useQuery<any>({
    queryKey: ["m-college"],
    queryFn: canteensApi.getCollegeSettings,
  });

  const {
    data: canteens = [],
    isError: canteensErr,
    error: canteensErrObj,
    refetch: refetchCanteens,
  } = useQuery<any[]>({
    queryKey: ["m-canteens"],
    queryFn: canteensApi.listCanteens,
    refetchInterval: 10000,
  });
  const activeCanteen = canteens.find((c) => c.id === selectedCanteenId) || canteens[0];

  const { data: categories = [] } = useQuery<any[]>({
    queryKey: ["m-categories", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: () => menuApi.listCategories(activeCanteen.id),
    refetchInterval: 8000,
  });

  const { data: promotions = [] } = useQuery<any[]>({
    queryKey: ["m-promotions", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: () => canteensApi.listActivePromotions(activeCanteen.id),
  });

  const { data: announcements = [] } = useQuery<any[]>({
    queryKey: ["m-announcements"],
    queryFn: canteensApi.listAnnouncements,
  });

  const { data: myOrders = [] } = useQuery<any[]>({
    queryKey: ["m-orders"],
    enabled: Boolean(user),
    queryFn: ordersApi.listMyOrders,
    refetchInterval: 10000,
  });
  const liveOrder = myOrders.find((o) => ACTIVE_STATUSES.has(o.status));

  const { data: profile } = useQuery<any>({
    queryKey: ["m-profile"],
    enabled: Boolean(user),
    queryFn: profileApi.getProfile,
  });

  const {
    data: items = [],
    isLoading: itemsLoading,
    isError: itemsErr,
    error: itemsErrObj,
    refetch: refetchItems,
  } = useQuery<any[]>({
    queryKey: ["m-items", activeCanteen?.id, search, selectedCategoryId, vegFilter, tagFilter, sortBy],
    enabled: Boolean(activeCanteen?.id),
    refetchInterval: 8000,
    queryFn: () =>
      menuApi.listItems(activeCanteen.id, {
        q: search,
        categoryId: selectedCategoryId,
        vegFilter,
        tagFilter,
        sortBy,
      }),
  });

  const { data: cart } = useQuery<any>({
    queryKey: ["m-cart", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: () => cartApi.getCart(activeCanteen.id),
  });

  const { data: itemReviews = [] } = useQuery<any[]>({
    queryKey: ["m-item-reviews", activeItem?.id],
    enabled: Boolean(activeItem?.id),
    queryFn: () => menuApi.getItemReviews(activeItem.id),
  });

  const openModal = (item: any) => {
    setActiveItem(item);
    const defVar =
      item.variants?.find((v: any) => v.is_default && v.is_available) ||
      item.variants?.find((v: any) => v.is_available) ||
      item.variants?.[0];
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
      return cartApi.addItem({
        canteen_id: activeCanteen.id,
        food_item_id: activeItem.id,
        variant_id: selVariantId || null,
        quantity: qty,
        spice_level: selSpice || null,
        sugar_level: selSugar || null,
        removed_ingredients: selRemoved,
        addons,
        special_instructions: instructions.trim() || null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["m-cart", activeCanteen?.id] });
      setActiveItem(null);
    },
    onError: (e: unknown) => setModalMsg(getMobileApiError(e, "Could not add item")),
  });

  const toggleFav = async (foodId: string) => {
    if (!user) return;
    try {
      const isFav = profile?.favourite_item_ids?.includes(foodId);
      if (isFav) await profileApi.removeFavourite(foodId);
      else await profileApi.addFavourite(foodId);
      qc.invalidateQueries({ queryKey: ["m-profile"] });
      qc.invalidateQueries({ queryKey: ["m-favourites"] });
    } catch {
      // keep silent on quick toggle failure
    }
  };

  const submitReview = async () => {
    if (!activeItem) return;
    try {
      await menuApi.submitReview({
        food_item_id: activeItem.id,
        rating: reviewRating,
        comment: reviewComment.trim() || null,
      });
      setReviewComment("");
      qc.invalidateQueries({ queryKey: ["m-item-reviews", activeItem.id] });
      qc.invalidateQueries({ queryKey: ["m-items"] });
      setModalMsg("Review submitted!");
    } catch (e: unknown) {
      setModalMsg(getMobileApiError(e, "Sign in to submit review"));
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

  const itemDisabled =
    Boolean(activeItem) &&
    (!activeItem.is_available ||
      activeItem.insufficient_ingredients ||
      activeItem.is_schedule_active_now === false ||
      !activeCanteen?.is_open_now);

  return (
    <View style={styles.container}>
      {/* College branding + Announcements + Live Board */}
      <View style={styles.topRow}>
        <BrandLogo size={38} />
        <View style={{ flex: 1, marginHorizontal: 10 }}>
          <Text style={styles.collegeTitle} numberOfLines={1}>
            {college?.college_name || "CollegeBites Campus"}
          </Text>
          <Text style={styles.brandSub} numberOfLines={1}>
            {announcements[0]?.title ||
              promotions[0]?.title ||
              (activeCanteen
                ? `${activeCanteen.location || activeCanteen.name} • ${
                    activeCanteen.is_open_now ? "Accepting Orders" : "Currently Closed"
                  }`
                : "Select a canteen")}
          </Text>
        </View>
        <View style={{ flexDirection: "row", gap: 6 }}>
          <Pressable onPress={() => router.push("/scan")} style={[styles.boardChip, { backgroundColor: "#1e293b" }]}>
            <Text style={styles.boardChipTxt}>Scan QR</Text>
          </Pressable>
          <Pressable onPress={() => router.push("/board")} style={styles.boardChip}>
            <Text style={styles.boardChipTxt}>Display →</Text>
          </Pressable>
        </View>
      </View>

      {liveOrder && (
        <Pressable onPress={() => router.push(`/order/${liveOrder.order_number}`)} style={styles.activeTrackBanner}>
          <View>
            <Text style={styles.activeTrackTitle}>
              Active Order {liveOrder.pickup_token_code ? `• Token ${liveOrder.pickup_token_code}` : ""}
            </Text>
            <Text style={styles.activeTrackSub}>
              {liveOrder.canteen_name} • {liveOrder.status}
            </Text>
          </View>
          <Text style={styles.activeTrackCta}>Track →</Text>
        </Pressable>
      )}

      {(canteensErr || itemsErr) && (
        <View style={styles.errBox}>
          <Text style={styles.errTxt}>
            {getMobileApiError(canteensErr ? canteensErrObj : itemsErrObj, "Unable to reach canteen backend")}
          </Text>
          <Pressable
            onPress={() => {
              refetchCanteens();
              refetchItems();
            }}
            style={styles.retryChip}
          >
            <Text style={styles.retryTxt}>Retry</Text>
          </Pressable>
        </View>
      )}

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
              <Text style={[styles.canteenTitle, active && { color: "#fff" }]}>
                {c.name} {!c.is_open_now ? "(Closed)" : ""}
              </Text>
              <Text style={[styles.canteenSub, active && { color: "#fdedce" }]}>
                {c.location ? `${c.location} • ` : ""}
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
            style={[styles.chip, tagFilter === tg && { backgroundColor: "#76010d", borderColor: "#76010d" }]}
          >
            <Text style={[styles.chipTxt, tagFilter === tg && { color: "#fff" }]}>
              {tg === "special" ? "Today's Special" : tg}
            </Text>
          </Pressable>
        ))}
      </ScrollView>

      <FlatList
        data={items}
        keyExtractor={(item) => item.id}
        contentContainerStyle={{ paddingBottom: 95, gap: 10 }}
        ListEmptyComponent={
          <View style={{ alignItems: "center", gap: 10, marginTop: 28, padding: 16 }}>
            <BrandLogo size={56} />
            <Text style={{ textAlign: "center", color: "#5d010a", fontWeight: "700", fontSize: 13 }}>
              {itemsLoading ? "Loading canteen menu..." : "No dishes matched your filters."}
            </Text>
          </View>
        }
        renderItem={({ item }) => {
          const outOfSchedule = item.is_schedule_active_now === false;
          const unavailable =
            !item.is_available || item.insufficient_ingredients || outOfSchedule || !activeCanteen?.is_open_now;
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
                  ₹{item.base_price} • {item.prep_time_minutes}m
                  {Number(item.average_rating) > 0 ? ` • ★ ${item.average_rating}` : ""}
                </Text>
              </View>
              <Pressable
                disabled={unavailable}
                onPress={() => openModal(item)}
                style={[styles.addBtn, unavailable && { backgroundColor: "#cbd5e1" }]}
              >
                <Text style={styles.addBtnText}>
                  {outOfSchedule ? "Off-Hours" : unavailable ? "Unavail" : "Customize"}
                </Text>
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
            {(activeItem.portion_size || activeItem.calories != null) && (
              <Text style={{ fontSize: 12, color: "#334155", fontWeight: "700" }}>
                {activeItem.portion_size ? `Portion: ${activeItem.portion_size}` : ""}
                {activeItem.portion_size && activeItem.calories != null ? " • " : ""}
                {activeItem.calories != null ? `${activeItem.calories} kcal` : ""}
              </Text>
            )}
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
                      disabled={!v.is_available}
                      onPress={() => setSelVariantId(v.id)}
                      style={[styles.optRow, active && styles.optRowActive, !v.is_available && { opacity: 0.45 }]}
                    >
                      <Text style={{ fontWeight: "700" }}>{v.name}{!v.is_available ? " (Out)" : ""}</Text>
                      <Text style={{ fontWeight: "800", color: "#76010d" }}>₹{p.toFixed(2)}</Text>
                    </Pressable>
                  );
                })}
              </View>
            )}

            {activeItem.addons?.filter((ad: any) => ad.is_available !== false).length > 0 && (
              <View style={styles.secBox}>
                <Text style={styles.secTitle}>Add-ons & Extra Toppings</Text>
                {activeItem.addons
                  .filter((ad: any) => ad.is_available !== false)
                  .map((ad: any) => {
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
                            onPress={() =>
                              setSelAddons((p) => ({ ...p, [ad.id]: Math.min(ad.max_quantity || 10, cnt + 1) }))
                            }
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
              <Pressable
                disabled={itemDisabled || addMut.isPending}
                onPress={() => addMut.mutate()}
                style={[styles.addBtn, { flex: 1, alignItems: "center", paddingVertical: 14 }, itemDisabled && { backgroundColor: "#cbd5e1" }]}
              >
                <Text style={styles.addBtnText}>
                  {itemDisabled ? "Currently Unavailable" : `Est. ₹${modalPrice.toFixed(2)} • Add to Cart`}
                </Text>
              </Pressable>
            </View>

            {Boolean(modalMsg) && <Text style={{ color: "#76010d", fontWeight: "700" }}>{modalMsg}</Text>}

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
  container: { flex: 1, backgroundColor: "#fdf8f0", padding: 12 },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  collegeTitle: { fontSize: 13, fontWeight: "900", color: "#380106" },
  brandSub: { fontSize: 11, fontWeight: "600", color: "#475569" },
  boardChip: { backgroundColor: "#380106", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 12 },
  boardChipTxt: { color: "#fff", fontSize: 11, fontWeight: "700" },
  activeTrackBanner: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#ffffff",
    borderColor: "#76010d",
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginBottom: 8,
  },
  activeTrackTitle: { fontSize: 12, fontWeight: "900", color: "#380106" },
  activeTrackSub: { fontSize: 11, color: "#76010d", marginTop: 1 },
  activeTrackCta: { fontSize: 12, fontWeight: "900", color: "#76010d" },
  errBox: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#fee2e2",
    borderRadius: 10,
    padding: 10,
    marginBottom: 8,
  },
  errTxt: { flex: 1, color: "#991b1b", fontSize: 12, fontWeight: "700" },
  retryChip: { backgroundColor: "#991b1b", borderRadius: 8, paddingHorizontal: 10, paddingVertical: 5 },
  retryTxt: { color: "#fff", fontSize: 11, fontWeight: "800" },
  canteenBar: { maxHeight: 62, marginBottom: 8 },
  canteenPill: { backgroundColor: "#fff", borderRadius: 12, padding: 10, marginRight: 8, borderWidth: 1, borderColor: "#e7d7c9" },
  canteenPillActive: { backgroundColor: "#380106", borderColor: "#380106" },
  canteenTitle: { fontWeight: "700", fontSize: 13, color: "#0f172a" },
  canteenSub: { fontSize: 11, color: "#64748b", marginTop: 2 },
  searchRow: { flexDirection: "row", gap: 6, marginBottom: 8 },
  searchInput: { flex: 1, backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#cbd5e1", paddingHorizontal: 12, paddingVertical: 8 },
  vegBtn: { justifyContent: "center", paddingHorizontal: 11, borderRadius: 12, borderWidth: 1, borderColor: "#cbd5e1", backgroundColor: "#fff" },
  vegText: { fontWeight: "700", fontSize: 12, color: "#0f172a" },
  chipBar: { maxHeight: 38, marginBottom: 8 },
  chip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 18, backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd5e1", marginRight: 6 },
  chipActive: { backgroundColor: "#380106", borderColor: "#380106" },
  chipTxt: { fontSize: 12, fontWeight: "700", color: "#334155" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 12, flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderColor: "#e7d7c9" },
  thumb: { width: 64, height: 64, borderRadius: 10, backgroundColor: "#e2e8f0" },
  itemTitle: { fontWeight: "800", fontSize: 14, color: "#0f172a", flex: 1 },
  itemDesc: { fontSize: 11, color: "#64748b", marginTop: 2 },
  itemMeta: { fontSize: 12, fontWeight: "700", color: "#76010d", marginTop: 4 },
  addBtn: { backgroundColor: "#76010d", borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  addBtnText: { color: "#fff", fontWeight: "700", fontSize: 12 },
  cartBar: { position: "absolute", bottom: 14, left: 14, right: 14, backgroundColor: "#380106", borderRadius: 14, padding: 14, flexDirection: "row", justifyContent: "space-between" },
  cartBarText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  modalWrap: { flex: 1, backgroundColor: "#fdf8f0", padding: 16 },
  closeBtn: { backgroundColor: "#fdedce", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8 },
  heroImg: { width: "100%", height: 180, borderRadius: 14, backgroundColor: "#e2e8f0" },
  secBox: { backgroundColor: "#fff", borderRadius: 12, padding: 12, gap: 8, borderWidth: 1, borderColor: "#e7d7c9" },
  secTitle: { fontWeight: "800", fontSize: 13, color: "#0f172a" },
  optRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 10, borderRadius: 10, borderWidth: 1, borderColor: "#e2e8f0" },
  optRowActive: { borderColor: "#76010d", backgroundColor: "#fdf8f0" },
  qtyBtn: { width: 32, height: 32, borderRadius: 8, backgroundColor: "#e2e8f0", alignItems: "center", justifyContent: "center" },
});
