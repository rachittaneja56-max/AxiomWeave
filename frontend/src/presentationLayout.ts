import type { PresentationDocument } from "./types";

export type PresentationSlide = PresentationDocument["slides"][number];

export type PresentationLayoutKind =
  "fact_cards" | "timeline" | "comparison" | "schedule" | "standard";

export function resolvePresentationLayout(
  slide: PresentationSlide,
): PresentationLayoutKind {
  const guidance = slide.visual_recommendation.toLowerCase();
  if (/\b(timeline|milestone|chronology)\b/.test(guidance)) return "timeline";
  if (/\b(schedule|maintenance|weekly)\b/.test(guidance)) return "schedule";
  if (
    /\b(channel|channels|compare|comparison|two[- ]column)\b/.test(guidance)
  ) {
    return "comparison";
  }
  if (/\b(scope|summary|facts|metrics|budget|launch)\b/.test(guidance)) {
    return "fact_cards";
  }
  return "standard";
}

export function getScheduleItems(bullets: string[]) {
  const primaryIndex = bullets.findIndex((bullet) =>
    /\b(schedule|maintenance|weekly)\b/i.test(bullet),
  );
  const selectedIndex = primaryIndex < 0 ? 0 : primaryIndex;
  return {
    primary: bullets[selectedIndex],
    supporting: bullets.filter((_, index) => index !== selectedIndex),
  };
}
