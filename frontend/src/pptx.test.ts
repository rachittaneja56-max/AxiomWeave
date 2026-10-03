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
      visual_recommendation: "DO_NOT_SHOW_THIS_LAYOUT_INSTRUCTION",
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
    const allSlideXml = await Promise.all(
      slideFiles.map((name) => archive.file(name)!.async("string")),
    );
    const notesXml = await archive.file(noteFiles[0]!)!.async("string");
    expect(slideXml).toContain("₹12 lakh");
    expect(slideXml).toContain("The community space opened Saturday");
    expect(slideXml).toContain("A welcoming opening");
    expect(slideXml).toContain("Residents attended");
    expect(allSlideXml.join(" ")).not.toContain("VISUAL DIRECTION");
    expect(allSlideXml.join(" ")).not.toContain(
      "DO_NOT_SHOW_THIS_LAYOUT_INSTRUCTION",
    );
    expect(allSlideXml.join(" ")).not.toContain("<p:pic");
    expect(notesXml).not.toContain("DO_NOT_SHOW_THIS_LAYOUT_INSTRUCTION");
    expect(notesXml).toContain("Welcome the neighbors");
  });

  it("preserves Project Asteria wording across deterministic layouts", async () => {
    const deck: PresentationDocument = {
      title: "Project Asteria",
      slides: [
        {
          title: "Pilot scope and ownership",
          key_message: "The pilot launches on 15 November 2026.",
          bullets: [
            "18 wards",
            "Maya Sen",
            "₹2.4 crore",
            "Hardware replacement exception",
          ],
          visual_recommendation: "Scope facts in a simple card grid.",
          speaker_notes: "Explain the pilot scope.",
        },
        {
          title: "Public channels and maintenance",
          key_message: "Use the published channels during maintenance.",
          bullets: [
            "SMS and city portal",
            "Friday 18:00 maintenance",
            "Holiday exception",
            "Severe-weather channel priority",
          ],
          visual_recommendation: "Compare channels and highlight the schedule.",
          speaker_notes: "Explain channel priorities.",
        },
        {
          title: "Launch and first review",
          key_message: "The formal review follows the pilot launch.",
          bullets: ["15 November 2026 launch", "15 February 2027 review"],
          visual_recommendation: "A two-point chronology timeline.",
          speaker_notes: "Cover the launch and review dates.",
        },
      ],
    };
    const archive = await JSZip.loadAsync(await renderPresentationPptx(deck));
    const slideFiles = Object.keys(archive.files).filter((name) =>
      /^ppt\/slides\/slide\d+\.xml$/.test(name),
    );
    const slideXml = await Promise.all(
      slideFiles.map((name) => archive.file(name)!.async("string")),
    );
    const text = slideXml.join(" ");
    for (const fact of [
      "15 November 2026",
      "18 wards",
      "Maya Sen",
      String.fromCharCode(8377) + "2.4 crore",
      "Hardware replacement exception",
      "SMS and city portal",
      "Friday 18:00 maintenance",
      "Holiday exception",
      "Severe-weather channel priority",
      "15 February 2027",
    ]) {
      expect(text).toContain(fact);
    }
    expect(text).not.toContain("Scope facts in a simple card grid");
    expect(text).not.toContain("Compare channels and highlight the schedule");
    expect(text).not.toContain("A two-point chronology timeline");
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
