import React from "react";
import { Image, StyleSheet, View } from "react-native";

const BRAND_LOGO = require("../../assets/brand-logo.png");

export function BrandLogo({
  size = 40,
  darkBg = false,
}: {
  size?: number;
  darkBg?: boolean;
}) {
  const radius = Math.max(8, Math.round(size * 0.24));
  return (
    <View
      style={[
        styles.wrap,
        {
          width: size,
          height: size,
          borderRadius: radius,
          borderColor: darkBg ? "rgba(255,255,255,0.28)" : "rgba(118,1,13,0.22)",
        },
      ]}
    >
      <Image
        source={BRAND_LOGO}
        resizeMode="contain"
        accessibilityLabel="CollegeBites logo"
        style={{ width: size - 4, height: size - 4, borderRadius: Math.max(6, radius - 2) }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: "#fdf8f0",
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
    padding: 2,
  },
});
