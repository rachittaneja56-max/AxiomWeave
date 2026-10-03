export function markdownWithoutDuplicateHeading(
  content: string,
  artifactLabel: string,
): string {
  const lines = content.split(/\r?\n/);
  const firstContentLine = lines.findIndex((line) => line.trim().length > 0);
  if (firstContentLine < 0) return content;

  const match = lines[firstContentLine]!.match(
    /^ {0,3}#{1,2}\s+(.+?)\s*#*\s*$/,
  );
  if (!match) return content;

  const heading = match[1]!
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  const normalizedLabel = artifactLabel.replace(/\s+/g, " ").trim();
  if (heading !== normalizedLabel) return content;

  lines.splice(firstContentLine, 1);
  return lines.join("\n");
}
