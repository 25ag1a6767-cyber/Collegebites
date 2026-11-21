import React from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import type { StripePayButtonProps } from "./StripePayButton";

export type { StripePayButtonProps };

export const StripePayButton: React.FC<StripePayButtonProps> = ({
  order,
  onError,
}) => {
  const openLegacyCheckout = async () => {
    if (order?.stripe_checkout_url) {
      await Linking.openURL(order.stripe_checkout_url);
      return;
    }
    onError("Use CollegeBites native mobile app or web Elements checkout to confirm Stripe PaymentIntent.");
  };

  return (
    <View style={styles.wrap}>
      {order?.stripe_checkout_url ? (
        <Pressable onPress={openLegacyCheckout} style={styles.btn}>
          <Text style={styles.btnTxt}>Open Stripe Checkout</Text>
        </Pressable>
      ) : (
        <Text style={styles.note}>
          {order?.stripe_payment_intent_id?.startsWith("pi_test_cb_")
            ? "Test-mode PaymentIntent created. Confirm via Stripe webhook or server merchant activation."
            : "Complete payment on CollegeBites iOS/Android dev build or web checkout."}
        </Text>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  btn: { backgroundColor: "#4f46e5", borderRadius: 10, padding: 12, alignItems: "center" },
  btnTxt: { color: "#fff", fontWeight: "800" },
  note: { color: "#64748b", fontSize: 12 },
});
