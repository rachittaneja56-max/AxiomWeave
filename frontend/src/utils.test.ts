import { describe, expect, it } from "vitest";
import {
  artifactExportText,
  deriveTransformationTitle,
  parseInfographic,
  parseVideoPackage,
} from "./utils";

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

describe("structured artifact review and exports", () => {
  const infographic = JSON.stringify({
    title: "Clinic facts",
    subtitle: "A short card",
    key_message: "The clinic opens Monday.",
    blocks: [
      { type: "section", heading: "Hours", body: "Check the posted schedule." },
      {
        type: "data",
        heading: "Opening",
        rows: [{ label: "Day", value: "Monday", note: "Fictional fixture" }],
      },
    ],
    visual_direction: "Use a simple calendar illustration.",
  });
  const videoPackage = JSON.stringify({
    title: "Clinic update",
    concept: "Share the opening day.",
    scenes: [
      {
        title: "Opening day",
        narration: "The clinic opens Monday.",
        on_screen_text: ["Opens Monday"],
        visual_direction: "Show the clinic entrance.",
        transition_notes: "Fade out.",
      },
    ],
  });

  it("shows readable structured exports without JSON syntax", () => {
    const infographicExport = artifactExportText("infographic", infographic);
    const videoExport = artifactExportText("video_package", videoPackage);
    expect(infographicExport).toContain("# Clinic facts");
    expect(infographicExport).toContain("Day: Monday");
    expect(infographicExport).toContain("Visual direction");
    expect(videoExport).toContain("## Scene 1: Opening day");
    expect(videoExport).toContain("The clinic opens Monday.");
    expect(videoExport).toContain("On-screen text: Opens Monday");
    expect(infographicExport).not.toContain('"blocks"');
    expect(videoExport).not.toContain('"scenes"');
  });

  it("rejects malformed structured content safely", () => {
    expect(parseInfographic('{"title":"Bad","unknown":true}')).toBeNull();
    expect(parseVideoPackage('{"title":"Bad","scenes":[]}')).toBeNull();
    expect(artifactExportText("infographic", "not json")).toBe(
      "This infographic specification could not be exported.",
    );
    expect(artifactExportText("video_package", "not json")).toBe(
      "This video package could not be exported.",
    );
  });
});
