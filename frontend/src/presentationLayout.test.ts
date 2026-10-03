import { describe, expect, it } from "vitest";
import {
  getScheduleItems,
  resolvePresentationLayout,
} from "./presentationLayout";
import type { PresentationDocument } from "./types";

const slide: PresentationDocument["slides"][number] = {
  title: "Example",
  key_message: "Existing key message",
  bullets: ["First fact", "Second fact"],
  visual_recommendation: "",
  speaker_notes: "",
};

describe("resolvePresentationLayout", () => {
  it.each([
    ["Scope facts in cards", "fact_cards"],
    ["A two-point milestone chronology", "timeline"],
    ["Compare communication channels", "comparison"],
    ["Weekly maintenance schedule", "schedule"],
    ["A calm photo with generous space", "standard"],
  ] as const)("resolves %s to %s", (guidance, kind) => {
    expect(
      resolvePresentationLayout({ ...slide, visual_recommendation: guidance }),
    ).toBe(kind);
  });

  it("gives the existing maintenance bullet the schedule emphasis", () => {
    expect(
      getScheduleItems([
        "SMS and city portal",
        "Friday 18:00 maintenance",
        "Holiday exception",
      ]),
    ).toEqual({
      primary: "Friday 18:00 maintenance",
      supporting: ["SMS and city portal", "Holiday exception"],
    });
  });
});
