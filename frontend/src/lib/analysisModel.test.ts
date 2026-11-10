import { describe, expect, it } from "vitest";

import type { ZigzagAnalysisConfig } from "../api/types";
import { describeConfig } from "./analysisModel";

const zigzag: ZigzagAnalysisConfig = {
  kind: "zigzag",
  epsilons: [0.05, 0.1],
  max_dimension: 1,
  normalization: "ideal_nadir",
  middle: "rips",
  representatives: 10,
};

describe("describeConfig", () => {
  it("names the complex at Rₜ when it is not Vietoris–Rips", () => {
    expect(describeConfig(zigzag)).toBe("zigzag · ε 0.05, 0.1 · H₀–H₁ · ideal–nadir");
    expect(describeConfig({ ...zigzag, middle: "union" })).toBe(
      "zigzag · ε 0.05, 0.1 · H₀–H₁ · ideal–nadir · union VR(Pₜ₋₁ ∪ Pₜ)",
    );
    expect(describeConfig({ ...zigzag, middle: "bridge_union" })).toBe(
      "zigzag · ε 0.05, 0.1 · H₀–H₁ · ideal–nadir · bridge over VR(Pₜ₋₁ ∪ Pₜ) (retired)",
    );
  });
});
