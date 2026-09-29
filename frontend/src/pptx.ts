import pptxgen from "pptxgenjs";
import type { PresentationDocument } from "./types";

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
    const longBullets =
      bulletCharacters > 650 ||
      item.bullets.some((bullet) => bullet.length > 220);
    const slide = pptx.addSlide();
    slide.background = { color: "FAF9F5" };
    slide.addShape(pptx.ShapeType.rect, {
      x: 0.55,
      y: 0.55,
      w: 0.12,
      h: 6.35,
      line: { color: "0F766E", transparency: 100 },
      fill: { color: "0F766E" },
    });
    slide.addText(presentation.title, {
      x: 0.9,
      y: 0.48,
      w: 10.9,
      h: 0.28,
      fontFace: "Aptos",
      fontSize: 10,
      color: "50716D",
      breakLine: false,
      margin: 0,
      fit: "shrink",
    });
    slide.addText(item.title, {
      x: 0.9,
      y: 1.0,
      w: 11.5,
      h: 0.85,
      fontFace: "Aptos Display",
      fontSize: item.title.length > 78 ? 22 : item.title.length > 54 ? 25 : 31,
      bold: true,
      color: "172B3A",
      margin: 0.02,
      breakLine: false,
      valign: "middle",
      fit: "shrink",
    });
    slide.addText(item.key_message, {
      x: 0.92,
      y: 2.0,
      w: 11.25,
      h: 0.72,
      fontFace: "Aptos",
      fontSize:
        item.key_message.length > 170
          ? 14
          : item.key_message.length > 120
            ? 16
            : 19,
      bold: true,
      color: "0F766E",
      margin: 0.02,
      valign: "middle",
      fit: "shrink",
    });
    const bulletFontSize = longBullets ? 12 : item.bullets.length > 4 ? 15 : 18;
    slide.addText(
      item.bullets.map((text) => ({
        text,
        options: {
          bullet: { indent: bulletFontSize },
          hanging: 4,
          breakLine: true,
        },
      })),
      {
        x: 1.02,
        y: 2.95,
        w: 10.95,
        h: 2.35,
        fontFace: "Aptos",
        fontSize: bulletFontSize,
        color: "263746",
        paraSpaceAfter: 10,
        margin: 0.05,
        valign: "top",
        fit: "shrink",
      },
    );
    slide.addShape(pptx.ShapeType.roundRect, {
      x: 0.95,
      y: 5.45,
      w: 11.3,
      h: 1.4,
      rectRadius: 0.08,
      line: { color: "D5E5DF", width: 1 },
      fill: { color: "F0F5F1" },
    });
    slide.addText("VISUAL DIRECTION", {
      x: 1.16,
      y: 5.6,
      w: 2.0,
      h: 0.2,
      fontFace: "Aptos",
      fontSize: 9,
      bold: true,
      charSpacing: 0.8,
      color: "50716D",
      margin: 0,
    });
    slide.addText(item.visual_recommendation, {
      x: 1.16,
      y: 5.85,
      w: 10.75,
      h: 0.88,
      fontFace: "Aptos",
      fontSize: item.visual_recommendation.length > 260 ? 10 : 12,
      color: "263746",
      margin: 0.01,
      fit: "shrink",
      valign: "middle",
    });
    slide.addText(
      `${String(index + 1).padStart(2, "0")} / ${String(presentation.slides.length).padStart(2, "0")}`,
      {
        x: 11.2,
        y: 7.08,
        w: 1.15,
        h: 0.2,
        fontFace: "Aptos",
        fontSize: 9,
        color: "718087",
        align: "right",
        margin: 0,
      },
    );
    slide.addNotes(item.speaker_notes);
  }
  return (await pptx.write({ outputType: "blob" })) as Blob;
}

export function presentationFilename(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `${slug || "axiomweave-presentation"}.pptx`;
}
