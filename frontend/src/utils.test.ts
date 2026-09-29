import { describe, expect, it } from "vitest";
import { deriveTransformationTitle } from "./utils";

describe("deriveTransformationTitle", () => {
  it("removes a trailing prompt number from a heading", () => {
    expect(deriveTransformationTitle("# Quarterly Review (Prompt 6)")).toBe(
      "Quarterly Review",
    );
    expect(
      deriveTransformationTitle(
        "EvidenceGate Final Audit Walkthrough (Prompt 12)",
      ),
    ).toBe("EvidenceGate Final Audit Walkthrough");
  });

  it("preserves other parentheticals and non-trailing prompt text", () => {
    expect(deriveTransformationTitle("Community Plan (Phase 2)")).toBe(
      "Community Plan (Phase 2)",
    );
    expect(deriveTransformationTitle("Prompt 6 explains the process.")).toBe(
      "Prompt 6 explains the process.",
    );
  });
});
