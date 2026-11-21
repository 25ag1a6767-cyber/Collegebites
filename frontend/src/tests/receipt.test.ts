import { describe, expect, it } from "vitest";
import { crowdBadgeTone } from "../components/ui/Primitives";

describe("CollegeBites Web Utilities", () => {
  it("maps crowd levels to semantic badge tones", () => {
    expect(crowdBadgeTone("LOW")).toBe("green");
    expect(crowdBadgeTone("MODERATE")).toBe("amber");
    expect(crowdBadgeTone("HIGH")).toBe("red");
    expect(crowdBadgeTone("VERY_HIGH")).toBe("red");
    expect(crowdBadgeTone("TEMPORARILY_UNAVAILABLE")).toBe("slate");
  });
});
