import pptxgen from "pptxgenjs";
import type { PresentationDocument } from "./types";
import {
  getScheduleItems,
  resolvePresentationLayout,
} from "./presentationLayout";

const COLORS = {
  paper: "FAF9F5",
  navy: "172B3A",
  ink: "263746",
  teal: "0F766E",
  mint: "EAF2EE",
  border: "D8E4DD",
  muted: "718087",
  amber: "F5EBD7",
  amberLine: "D8B86C",
};

const CONTENT_X = 0.9;
const CONTENT_Y = 3.0;
const CONTENT_W = 11.55;
const CONTENT_H = 3.78;
type PowerPoint = InstanceType<typeof pptxgen>;

export async function renderPresentationPptx(
  presentation: PresentationDocument,
): Promise<Blob> {
  const pptx = new pptxgen();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "AxiomWeave";
  pptx.subject = "Editable AxiomWeave presentation";
  pptx.title = presentation.title;
  pptx.theme = {
    headFontFace: "Aptos Display",
    bodyFontFace: "Aptos",
  };

  for (const [index, item] of presentation.slides.entries()) {
    const bulletCharacters = item.bullets.reduce(
      (sum, bullet) => sum + bullet.length,
      0,
    );
    if (bulletCharacters > 900) {
      throw new Error(
        "This slide has too much bullet text to fit. Shorten the bullets and try again.",
      );
    }

    const slide = pptx.addSlide();
    slide.background = { color: COLORS.paper };
    slide.addShape(pptx.ShapeType.rect, {
      x: 0.5,
      y: 0.42,
      w: 0.09,
      h: 6.45,
      line: { color: COLORS.teal, transparency: 100 },
      fill: { color: COLORS.teal },
    });
    slide.addText(presentation.title, {
      x: CONTENT_X,
      y: 0.34,
      w: 10.8,
      h: 0.25,
      fontFace: "Aptos",
      fontSize: 10,
      color: "50716D",
      margin: 0,
      breakLine: false,
      fit: "shrink",
    });
    slide.addText(item.title, {
      x: CONTENT_X,
      y: 0.74,
      w: CONTENT_W,
      h: 0.75,
      fontFace: "Aptos Display",
      fontSize: item.title.length > 78 ? 23 : item.title.length > 54 ? 27 : 32,
      bold: true,
      color: COLORS.navy,
      margin: 0.02,
      breakLine: false,
      valign: "middle",
      fit: "shrink",
    });

    slide.addShape(pptx.ShapeType.roundRect, {
      x: CONTENT_X,
      y: 1.68,
      w: CONTENT_W,
      h: 0.93,
      rectRadius: 0.06,
      line: { color: "C9DDD4", width: 0.8 },
      fill: { color: COLORS.mint },
    });
    slide.addShape(pptx.ShapeType.rect, {
      x: CONTENT_X,
      y: 1.68,
      w: 0.07,
      h: 0.93,
      line: { color: COLORS.teal, transparency: 100 },
      fill: { color: COLORS.teal },
    });
    slide.addText(item.key_message, {
      x: CONTENT_X + 0.24,
      y: 1.81,
      w: CONTENT_W - 0.46,
      h: 0.66,
      fontFace: "Aptos",
      fontSize:
        item.key_message.length > 170
          ? 14
          : item.key_message.length > 120
            ? 16
            : 19,
      bold: true,
      color: COLORS.teal,
      margin: 0.02,
      valign: "middle",
      fit: "shrink",
    });

    const bullets = item.bullets.filter((bullet) => bullet.trim().length > 0);
    const layout = resolvePresentationLayout(item);
    if (layout === "timeline") {
      addTimeline(pptx, slide, bullets);
    } else if (layout === "schedule") {
      addSchedule(pptx, slide, bullets);
    } else if (layout === "comparison") {
      addComparison(pptx, slide, bullets);
    } else {
      addFactCards(pptx, slide, bullets, layout === "standard");
    }

    slide.addText(
      `${String(index + 1).padStart(2, "0")} / ${String(presentation.slides.length).padStart(2, "0")}`,
      {
        x: 11.3,
        y: 7.1,
        w: 1.1,
        h: 0.18,
        fontFace: "Aptos",
        fontSize: 9,
        color: COLORS.muted,
        align: "right",
        margin: 0,
      },
    );
    slide.addNotes(item.speaker_notes);
  }
  return (await pptx.write({ outputType: "blob" })) as Blob;
}

function addFactCards(
  pptx: PowerPoint,
  slide: pptxgen.Slide,
  bullets: string[],
  standard: boolean,
) {
  if (bullets.length === 0) return;
  const columns = bullets.length === 1 ? 1 : 2;
  const gapX = 0.18;
  const gapY = 0.14;
  const cardW = (CONTENT_W - gapX * (columns - 1)) / columns;
  const rows = Math.ceil(bullets.length / columns);
  const cardH = Math.min(1.12, (CONTENT_H - gapY * (rows - 1)) / rows);
  bullets.forEach((bullet, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const x = CONTENT_X + column * (cardW + gapX);
    const y = CONTENT_Y + row * (cardH + gapY);
    addCard(pptx, slide, bullet, x, y, cardW, cardH, {
      fill: standard ? "FFFFFF" : "F2F7F3",
      fontSize: bullet.length > 190 ? 13 : bullet.length > 115 ? 15 : 18,
      accent: standard ? "D8E4DD" : "8DBBAD",
    });
  });
}

function addSchedule(
  pptx: PowerPoint,
  slide: pptxgen.Slide,
  bullets: string[],
) {
  if (bullets.length === 0) return;
  const { primary, supporting } = getScheduleItems(bullets);
  if (!primary) return;
  const primaryH = Math.min(1.45, CONTENT_H * 0.39);
  addCard(pptx, slide, primary, CONTENT_X, CONTENT_Y, CONTENT_W, primaryH, {
    fill: COLORS.amber,
    accent: COLORS.amberLine,
    fontSize: primary.length > 150 ? 16 : 20,
  });
  if (supporting.length === 0) return;
  const top = CONTENT_Y + primaryH + 0.16;
  const height = CONTENT_H - primaryH - 0.16;
  const columns = supporting.length === 1 ? 1 : 2;
  const gapX = 0.18;
  const gapY = 0.12;
  const cardW = (CONTENT_W - gapX * (columns - 1)) / columns;
  const rows = Math.ceil(supporting.length / columns);
  const cardH = (height - gapY * (rows - 1)) / rows;
  supporting.forEach((bullet, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    addCard(
      pptx,
      slide,
      bullet,
      CONTENT_X + column * (cardW + gapX),
      top + row * (cardH + gapY),
      cardW,
      cardH,
      {
        fill: "FFFFFF",
        accent: "B8D1C7",
        fontSize: bullet.length > 145 ? 13 : 16,
      },
    );
  });
}

function addComparison(
  pptx: PowerPoint,
  slide: pptxgen.Slide,
  bullets: string[],
) {
  if (bullets.length === 0) return;
  const groupGap = 0.2;
  const groupW = (CONTENT_W - groupGap) / 2;
  const groups = [
    bullets.slice(0, Math.ceil(bullets.length / 2)),
    bullets.slice(Math.ceil(bullets.length / 2)),
  ];
  groups.forEach((group, groupIndex) => {
    if (group.length === 0) return;
    const x = CONTENT_X + groupIndex * (groupW + groupGap);
    const rowGap = 0.13;
    const cardH = Math.min(
      1.12,
      (CONTENT_H - 0.28 - rowGap * (group.length - 1)) / group.length,
    );
    slide.addShape(pptx.ShapeType.roundRect, {
      x,
      y: CONTENT_Y,
      w: groupW,
      h: CONTENT_H,
      rectRadius: 0.06,
      line: { color: "D8E4DD", width: 0.9 },
      fill: { color: groupIndex === 0 ? "F1F6F2" : "F8F4E9" },
    });
    group.forEach((bullet, index) => {
      addCard(
        pptx,
        slide,
        bullet,
        x + 0.14,
        CONTENT_Y + 0.14 + index * (cardH + rowGap),
        groupW - 0.28,
        cardH,
        {
          fill: "FFFFFF",
          accent: groupIndex === 0 ? "8DBBAD" : COLORS.amberLine,
          fontSize: bullet.length > 145 ? 13 : 16,
        },
      );
    });
  });
}

function addTimeline(
  pptx: PowerPoint,
  slide: pptxgen.Slide,
  bullets: string[],
) {
  if (bullets.length === 0) return;
  if (bullets.length <= 4) {
    const gap = 0.24;
    const cardW = (CONTENT_W - gap * (bullets.length - 1)) / bullets.length;
    const lineY = CONTENT_Y + 0.55;
    slide.addShape(pptx.ShapeType.line, {
      x: CONTENT_X + 0.12,
      y: lineY,
      w: CONTENT_W - 0.24,
      h: 0,
      line: { color: "86B8A8", width: 2 },
    });
    bullets.forEach((bullet, index) => {
      const x = CONTENT_X + index * (cardW + gap);
      slide.addShape(pptx.ShapeType.ellipse, {
        x: x + 0.04,
        y: lineY - 0.1,
        w: 0.2,
        h: 0.2,
        line: { color: COLORS.teal, width: 1 },
        fill: { color: "FFFFFF" },
      });
      addCard(
        pptx,
        slide,
        bullet,
        x,
        CONTENT_Y + 0.82,
        cardW,
        CONTENT_H - 0.82,
        {
          fill: "FFFFFF",
          accent: "8DBBAD",
          fontSize: bullet.length > 140 ? 13 : 17,
        },
      );
    });
    return;
  }

  const gap = 0.1;
  const rowH = (CONTENT_H - gap * (bullets.length - 1)) / bullets.length;
  slide.addShape(pptx.ShapeType.line, {
    x: CONTENT_X + 0.16,
    y: CONTENT_Y + 0.2,
    w: 0,
    h: CONTENT_H - 0.4,
    line: { color: "86B8A8", width: 2 },
  });
  bullets.forEach((bullet, index) => {
    slide.addShape(pptx.ShapeType.ellipse, {
      x: CONTENT_X + 0.06,
      y: CONTENT_Y + index * (rowH + gap) + rowH / 2 - 0.09,
      w: 0.19,
      h: 0.19,
      line: { color: COLORS.teal, width: 1 },
      fill: { color: "FFFFFF" },
    });
    addCard(
      pptx,
      slide,
      bullet,
      CONTENT_X + 0.42,
      CONTENT_Y + index * (rowH + gap),
      CONTENT_W - 0.42,
      rowH,
      {
        fill: "FFFFFF",
        accent: "8DBBAD",
        fontSize: bullet.length > 145 ? 12 : 15,
      },
    );
  });
}

function addCard(
  pptx: PowerPoint,
  slide: pptxgen.Slide,
  text: string,
  x: number,
  y: number,
  w: number,
  h: number,
  options: { fill: string; accent: string; fontSize: number },
) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.06,
    line: { color: COLORS.border, width: 0.8 },
    fill: { color: options.fill },
  });
  slide.addShape(pptx.ShapeType.rect, {
    x,
    y: y + 0.08,
    w: 0.055,
    h: Math.max(0.2, h - 0.16),
    line: { color: options.accent, transparency: 100 },
    fill: { color: options.accent },
  });
  slide.addText(text, {
    x: x + 0.2,
    y: y + 0.08,
    w: w - 0.34,
    h: Math.max(0.24, h - 0.16),
    fontFace: "Aptos",
    fontSize: options.fontSize,
    color: COLORS.ink,
    margin: 0.02,
    valign: "middle",
    breakLine: false,
    fit: "shrink",
  });
}

export function presentationFilename(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `${slug || "axiomweave-presentation"}.pptx`;
}
