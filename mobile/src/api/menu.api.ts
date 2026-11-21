import { mobileApi } from "./client";

export const menuApi = {
  listCategories: async (canteenId: string) =>
    (await mobileApi.get(`/menus/canteens/${canteenId}/categories`)).data,

  listItems: async (
    canteenId: string,
    params?: {
      q?: string;
      categoryId?: string;
      vegFilter?: "all" | "veg" | "nonveg";
      tagFilter?: "all" | "featured" | "popular" | "special";
      sortBy?: "popularity" | "price_asc" | "price_desc";
    }
  ) => {
    const qs: string[] = [`sort_by=${encodeURIComponent(params?.sortBy || "popularity")}`];
    if (params?.q?.trim()) qs.push(`q=${encodeURIComponent(params.q.trim())}`);
    if (params?.categoryId) qs.push(`category_id=${encodeURIComponent(params.categoryId)}`);
    if (params?.vegFilter === "veg") qs.push("is_veg=true");
    if (params?.vegFilter === "nonveg") qs.push("is_veg=false");
    if (params?.tagFilter === "featured") qs.push("featured=true");
    if (params?.tagFilter === "popular") qs.push("popular=true");
    if (params?.tagFilter === "special") qs.push("todays_special=true");
    return (await mobileApi.get(`/menus/canteens/${canteenId}/items?${qs.join("&")}`)).data;
  },

  getItemReviews: async (foodItemId: string) =>
    (await mobileApi.get(`/support/items/${foodItemId}/reviews`)).data,

  submitReview: async (payload: { food_item_id: string; order_id?: string | null; rating: number; comment?: string | null }) =>
    (await mobileApi.post("/support/reviews", payload)).data,
};
