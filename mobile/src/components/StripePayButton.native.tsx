import React, { useState } from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { initPaymentSheet, initStripe, presentPaymentSheet } from "@stripe/stripe-react-native";
import { getMobileApiError } from "../api/client";
import { paymentsApi } from "../api/payments.api";
import type { StripePayButtonProps } from "./StripePayButton";

export type { StripePayButtonProps };

export const StripePayButton: React.FC<StripePayButtonProps> = ({
  order,
  publishableKeyOverride,
  disabled,
  onVerified,
  onError,
}) => {
  const [busy, setBusy] = useState(false);
  const [needsRecovery, setNeedsRecovery] = useState(false);

  const publishableKey = order?.stripe_publishable_key || publishableKeyOverride || null;
  const clientSecret = order?.stripe_client_secret || null;
  const piId = order?.stripe_payment_intent_id || null;
  const isSimulated = Boolean(piId && piId.startsWith("pi_test_cb_"));

  const verifyWithBackend = async () => {
    if (!piId) return;
    setBusy(true);
    try {
      const verified = await paymentsApi.verifyStripe({
        order_id: order.id,
        stripe_payment_intent_id: piId,
        payment_method: "stripe",
      });
      if (verified?.payment_status === "CONFIRMED") {
        setNeedsRecovery(false);
        await onVerified();
      } else {
        setNeedsRecovery(true);
        onError("Stripe payment is processing. Tap 'Sync Payment Status' shortly.");
        await onVerified();
      }
    } catch (e: unknown) {
      setNeedsRecovery(true);
      onError(getMobileApiError(e, "Network issue verifying payment. Tap Sync Payment Status without paying again."));
    } finally {
      setBusy(false);
    }
  };

  const launchNativePaymentSheet = async () => {
    if (disabled || busy) return;
    if (order?.stripe_checkout_url && !clientSecret) {
      await Linking.openURL(order.stripe_checkout_url);
      return;
    }
    if (!publishableKey || !clientSecret || isSimulated) {
      onError(
        "Stripe online processing is awaiting server merchant activation in this environment."
      );
      return;
    }

    setBusy(true);
    onError("");
    try {
      await initStripe({
        publishableKey,
        urlScheme: "collegebites",
        setReturnUrlSchemeOnAndroid: true,
      });

      const initRes = await initPaymentSheet({
        merchantDisplayName: "CollegeBites",
        paymentIntentClientSecret: clientSecret,
        returnURL: "collegebites://stripe-redirect",
        allowsDelayedPaymentMethods: false,
      });
      if (initRes.error) {
        onError(initRes.error.message || "Unable to initialize Stripe PaymentSheet.");
        return;
      }

      const presentRes = await presentPaymentSheet();
      if (presentRes.error) {
        if (presentRes.error.code === "Canceled") {
          onError("Payment sheet dismissed. Tap Pay with Stripe to retry or Cancel Payment.");
        } else {
          onError(presentRes.error.message || "Stripe PaymentSheet authorization failed.");
        }
        return;
      }

      await verifyWithBackend();
    } catch (e: unknown) {
      onError(getMobileApiError(e, "Stripe payment could not be completed."));
    } finally {
      setBusy(false);
    }
  };

  const canPayNative = Boolean((publishableKey && clientSecret && !isSimulated) || order?.stripe_checkout_url);

  return (
    <View style={styles.wrap}>
      {canPayNative ? (
        <Pressable
          disabled={disabled || busy}
          onPress={needsRecovery ? verifyWithBackend : launchNativePaymentSheet}
          style={[styles.btn, (disabled || busy) && styles.btnDisabled]}
        >
          <Text style={styles.btnTxt}>
            {busy
              ? "Processing with Stripe..."
              : needsRecovery
              ? "Sync Payment Status"
              : `Pay ₹${order.total_amount} with Stripe`}
          </Text>
        </Pressable>
      ) : (
        <Text style={styles.note}>
          {isSimulated
            ? "Sandbox PaymentIntent ready (awaiting webhook or server merchant activation)."
            : "Stripe online processing is awaiting server merchant activation."}
        </Text>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  btn: { backgroundColor: "#4f46e5", borderRadius: 10, padding: 12, alignItems: "center" },
  btnDisabled: { opacity: 0.65 },
  btnTxt: { color: "#fff", fontWeight: "800" },
  note: { color: "#64748b", fontSize: 12 },
});
