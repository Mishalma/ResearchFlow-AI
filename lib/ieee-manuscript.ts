const SECTION_DEFINITIONS = [
  {
    id: "introduction",
    heading: "I. INTRODUCTION",
    pattern: /^(?:i\.?\s*)?introduction$/i,
  },
  {
    id: "related_work",
    heading: "II. RELATED WORK",
    pattern: /^(?:ii\.?\s*)?related work$/i,
  },
  {
    id: "methodology",
    heading: "III. METHODOLOGY",
    pattern: /^(?:iii\.?\s*)?methodology$/i,
  },
  {
    id: "results",
    heading: "IV. RESULTS",
    pattern: /^(?:iv\.?\s*)?results$/i,
  },
  {
    id: "discussion",
    heading: "V. DISCUSSION",
    pattern: /^(?:v\.?\s*)?discussion$/i,
  },
  {
    id: "limitations",
    heading: "VI. LIMITATIONS",
    pattern: /^(?:vi\.?\s*)?limitations$/i,
  },
  {
    id: "conclusion",
    heading: "VII. CONCLUSION",
    pattern: /^(?:vii\.?\s*)?conclusion$/i,
  },
] as const;

type SectionId = (typeof SECTION_DEFINITIONS)[number]["id"];

export type ParsedIeeeSection = {
  id: SectionId;
  heading: string;
  content: string;
};

export type ParsedIeeeManuscript = {
  abstract: string;
  keywords: string[];
  sections: ParsedIeeeSection[];
  references: string[];
};

function normalizeParagraphBlock(lines: string[]) {
  const joined = lines.join("\n").trim();
  if (!joined) {
    return "";
  }

  return joined
    .split(/\n\s*\n/)
    .map((paragraph) =>
      paragraph
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .join(" "),
    )
    .filter(Boolean)
    .join("\n\n");
}

export function parseIeeeManuscript(
  manuscript: string,
  fallbackKeywords: string[] = [],
): ParsedIeeeManuscript {
  const normalized = manuscript.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();

  const buffers: Record<SectionId | "abstract" | "references", string[]> = {
    abstract: [],
    introduction: [],
    related_work: [],
    methodology: [],
    results: [],
    discussion: [],
    limitations: [],
    conclusion: [],
    references: [],
  };
  let keywordsLine = "";
  let currentSection: keyof typeof buffers | "keywords" | null = null;

  for (const rawLine of normalized.split("\n")) {
    const line = rawLine.trim();

    if (/^abstract$/i.test(line)) {
      currentSection = "abstract";
      continue;
    }

    const inlineKeywordMatch = line.match(/^index terms\s*[-:]\s*(.*)$/i);
    if (inlineKeywordMatch) {
      keywordsLine = inlineKeywordMatch[1]?.trim() ?? "";
      currentSection = "keywords";
      continue;
    }

    if (/^index terms$/i.test(line)) {
      currentSection = "keywords";
      continue;
    }

    if (/^references$/i.test(line)) {
      currentSection = "references";
      continue;
    }

    const matchedSection = SECTION_DEFINITIONS.find((section) =>
      section.pattern.test(line),
    );
    if (matchedSection) {
      currentSection = matchedSection.id;
      continue;
    }

    if (currentSection === "keywords") {
      if (line) {
        keywordsLine = keywordsLine
          ? `${keywordsLine} ${line}`.trim()
          : line;
      }
      continue;
    }

    if (currentSection) {
      buffers[currentSection].push(rawLine);
    }
  }

  const keywords = (keywordsLine
    ? keywordsLine.split(",")
    : fallbackKeywords
  )
    .map((keyword) => keyword.trim())
    .filter(Boolean);

  const sections = SECTION_DEFINITIONS.map((section) => ({
    id: section.id,
    heading: section.heading,
    content:
      normalizeParagraphBlock(buffers[section.id]) ||
      "Section pending author input.",
  }));

  const references = buffers.references
    .map((reference) => reference.trim())
    .filter(Boolean);

  return {
    abstract:
      normalizeParagraphBlock(buffers.abstract) ||
      "Abstract pending author input.",
    keywords,
    sections,
    references:
      references.length > 0
        ? references
        : ["[1] Reference curation pending manual review."],
  };
}
