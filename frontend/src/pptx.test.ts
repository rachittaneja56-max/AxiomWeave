import { describe, expect, it } from "vitest";
import JSZip from "jszip";
import { presentationFilename, renderPresentationPptx } from "./pptx";
import type { PresentationDocument } from "./types";

const spec: PresentationDocument = {
  title: "Riverdale Update",
  slides: [
    {
      title: "A welcoming opening",
      key_message: "The community space opened Saturday; budget ₹12 lakh.",
      bullets: ["Residents attended", "The entrance is step-free"],
      visual_recommendation: "A simple entrance photo.",
      speaker_notes: "Welcome the neighbors and share the opening date.",
    },
    {
      title: "Next steps",
      key_message: "Visit during the posted hours.",
      bullets: ["Check the sign", "Ask staff for details"],
      visual_recommendation: "A small hours callout.",
      speaker_notes: "Thank attendees for joining us.",
    },
  ],
};

describe("PowerPoint export", () => {
  it("creates a non-empty editable PPTX blob from the validated slide spec", async () => {
    const blob = await renderPresentationPptx(spec);
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("application/zip");
    expect(blob.size).toBeGreaterThan(2_000);
    const archive = await JSZip.loadAsync(blob);
    const slideFiles = Object.keys(archive.files).filter((name) =>
      /^ppt\/slides\/slide\d+\.xml$/.test(name),
    );
    const noteFiles = Object.keys(archive.files).filter((name) =>
      /^ppt\/notesSlides\/notesSlide\d+\.xml$/.test(name),
    );
    expect(slideFiles).toHaveLength(2);
    expect(noteFiles).toHaveLength(2);
    const slideXml = await archive.file(slideFiles[0]!)!.async("string");
    const notesXml = await archive.file(noteFiles[0]!)!.async("string");
    expect(slideXml).toContain("₹12 lakh");
    expect(slideXml).toContain("The community space opened Saturday");
    expect(notesXml).toContain("Welcome the neighbors");
  });

  it("uses a title-based filename without technical identifiers", () => {
    expect(presentationFilename("Riverdale Update / 2026")).toBe(
      "riverdale-update-2026.pptx",
    );
    expect(presentationFilename("🌱")).toBe("axiomweave-presentation.pptx");
  });

  it("surfaces slides whose bullet text cannot fit instead of dropping content", async () => {
    const longSlide: PresentationDocument = {
      ...spec,
      slides: [
        { ...spec.slides[0]!, bullets: ["A".repeat(901)] },
        spec.slides[1]!,
      ],
    };
    await expect(renderPresentationPptx(longSlide)).rejects.toThrow(
      "This slide has too much bullet text to fit",
    );
  });
});
