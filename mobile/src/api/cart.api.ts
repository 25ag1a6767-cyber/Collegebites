import { mobileApi } from "./client";

export const cartApi = {
  getCart: async (canteenId: string) =>
    (await mobileApi.get(`/carts?canteen_id=${encodeURIComponent(canteenId)}`)).data,

  addItem: async (payload: {
    canteen_id: string;
    food_item_id: string;
    variant_id?: string | null;
    quantity: number;
    spice_level?: string | null;
    sugar_level?: string | null;
    removed_ingredients?: string[];
    addons?: Array<{ addon_id: string; quantity: number }>;
    special_instructions?: string | null;
  }) => (await mobileApi.post("/carts/items", payload)).data,

  updateItem: async (
    cartItemId: string,
    payload: {
      quantity?: number;
      variant_id?: string | null;
      spice_level?: string | null;
      sugar_level?: string | null;
      removed_ingredients?: string[];
      addons?: Array<{ addon_id: string; quantity: number }>;
      special_instructions?: string | null;
    }
  ) => (await mobileApi.patch(`/carts/items/${cartItemId}`, payload)).data,
};
