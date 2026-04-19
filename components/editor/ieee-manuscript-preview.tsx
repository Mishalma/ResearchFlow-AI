import {
  buildFigureAssetUrl,
  type FigureRecord,
  type GeneratedRenderedFigure,
} from "@/lib/backend";
import type { ParsedIeeeManuscript } from "@/lib/ieee-manuscript";

type IeeeManuscriptPreviewProps = {
  title: string;
  authors: string[];
  preview: ParsedIeeeManuscript;
  figures?: FigureRecord[];
  generatedFigures?: GeneratedRenderedFigure[];
  generatedTables?: GeneratedRenderedFigure[];
  projectId?: string | null;
};

type PreviewSectionId = ParsedIeeeManuscript["sections"][number]["id"];
type RenderableSectionId = PreviewSectionId | "abstract";

const SECTION_ALIAS_MAP: Record<string, RenderableSectionId> = {
  abstract: "abstract",
  intro: "introduction",
  introduction: "introduction",
  "related work": "related_work",
  "related works": "related_work",
  background: "related_work",
  "literature review": "related_work",
  method: "methodology",
  methods: "methodology",
  methodology: "methodology",
  approach: "methodology",
  "materials methods": "methodology",
  "materials and methods": "methodology",
  "experimental setup": "methodology",
  "system architecture": "methodology",
  results: "results",
  result: "results",
  evaluation: "results",
  experiments: "results",
  "experimental results": "results",
  findings: "results",
  discussion: "discussion",
  analysis: "discussion",
  limitations: "limitations",
  limitation: "limitations",
  "threats to validity": "limitations",
  conclusion: "conclusion",
  conclusions: "conclusion",
  "future work": "conclusion",
};

function splitParagraphs(text: string) {
  return text
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
}

export function IeeeManuscriptPreview({
  title,
  authors,
  preview,
  figures = [],
  generatedFigures = [],
  generatedTables = [],
  projectId,
}: IeeeManuscriptPreviewProps) {
  const figuresBySection = new Map<RenderableSectionId, FigureRecord[]>();
  const figureNumberById = new Map<string, number>();
  const generatedFiguresBySection = new Map<
    RenderableSectionId,
    GeneratedRenderedFigure[]
  >();
  const generatedTablesBySection = new Map<
    RenderableSectionId,
    GeneratedRenderedFigure[]
  >();
  const unmatchedFigures: FigureRecord[] = [];
  const unmatchedGeneratedFigures: GeneratedRenderedFigure[] = [];
  const unmatchedGeneratedTables: GeneratedRenderedFigure[] = [];

  figures.forEach((figure, index) => {
    figureNumberById.set(figure.id, index + 1);
    const resolvedSection = resolveSectionId(figure.section, preview);

    if (!resolvedSection) {
      unmatchedFigures.push(figure);
      return;
    }

    const bucket = figuresBySection.get(resolvedSection) ?? [];
    bucket.push(figure);
    figuresBySection.set(resolvedSection, bucket);
  });

  generatedFigures.forEach((figure, index) => {
    figureNumberById.set(
      figure.spec.id,
      figure.spec.figure_number ?? figures.length + index + 1,
    );

    const resolvedSection = resolveSectionId(
      figure.spec.section,
      preview,
      figure.spec.placement_hint,
    );

    if (!resolvedSection) {
      unmatchedGeneratedFigures.push(figure);
      return;
    }

    const bucket = generatedFiguresBySection.get(resolvedSection) ?? [];
    bucket.push(figure);
    generatedFiguresBySection.set(resolvedSection, bucket);
  });

  generatedTables.forEach((table) => {
    const resolvedSection = resolveSectionId(
      table.spec.section,
      preview,
      table.spec.placement_hint,
    );

    if (!resolvedSection) {
      unmatchedGeneratedTables.push(table);
      return;
    }

    const bucket = generatedTablesBySection.get(resolvedSection) ?? [];
    bucket.push(table);
    generatedTablesBySection.set(resolvedSection, bucket);
  });

  const hasFallbackVisuals =
    unmatchedFigures.length > 0 ||
    unmatchedGeneratedFigures.length > 0 ||
    unmatchedGeneratedTables.length > 0;

  function renderUploadedFigure(figure: FigureRecord) {
    if (!projectId) {
      return null;
    }

    return (
      <figure
        key={figure.id}
        className="mt-4 break-inside-avoid-column rounded-xl border border-slate-200 bg-slate-50 p-3"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={buildFigureAssetUrl(projectId, figure.id)}
          alt={figure.caption}
          className="max-h-64 w-full rounded-lg object-contain"
        />
        <figcaption className="mt-2 text-center text-[9pt] text-slate-700">
          <span className="font-semibold">
            Fig. {figureNumberById.get(figure.id)}.
          </span>{" "}
          {figure.caption}
        </figcaption>
      </figure>
    );
  }

  function renderGeneratedFigure(figure: GeneratedRenderedFigure) {
    const hasRenderableVisual = Boolean(figure.png_base64 || figure.svg_content);

    return (
      <figure
        key={figure.spec.id}
        className="mt-4 break-inside-avoid-column rounded-xl border border-slate-200 bg-slate-50 p-3"
      >
        {figure.png_base64 ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`data:image/png;base64,${figure.png_base64}`}
            alt={figure.spec.caption}
            className="max-h-64 w-full rounded-lg object-contain"
          />
        ) : figure.svg_content ? (
          <div
            className="flex justify-center"
            dangerouslySetInnerHTML={{ __html: figure.svg_content }}
          />
        ) : (
          <div className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-6 text-center text-[9pt] text-slate-500">
            Figure preview unavailable.
          </div>
        )}
        <figcaption className="mt-2 text-center text-[9pt] text-slate-700">
          <span className="font-semibold">
            Fig.{" "}
            {figure.spec.figure_number ?? figureNumberById.get(figure.spec.id)}.
          </span>{" "}
          {stripLeadingCaptionLabel(figure.spec.caption)}
        </figcaption>
        {!hasRenderableVisual && figure.render_error ? (
          <p className="mt-1 text-center text-[8.5pt] text-rose-600">
            {figure.render_error}
          </p>
        ) : null}
      </figure>
    );
  }

  function renderGeneratedTable(table: GeneratedRenderedFigure) {
    const headers = ((table.spec.data?.headers as unknown[]) ?? []).map((value) =>
      String(value),
    );
    const rows = normalizeGeneratedTableRows(
      table.spec.data?.rows,
      headers.length,
    );
    const hasTabularData = headers.length > 0 || rows.length > 0;

    return (
      <figure
        key={table.spec.id}
        className="mt-4 break-inside-avoid-column rounded-xl border border-slate-200 bg-slate-50 p-3"
      >
        {hasTabularData ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-[9pt] text-slate-800">
              <thead>
                <tr className="border-b border-slate-300">
                  {headers.map((header) => (
                    <th key={header} className="px-2 py-1 font-semibold">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, rowIndex) => (
                  <tr
                    key={`${table.spec.id}-${rowIndex}`}
                    className="border-b border-slate-200"
                  >
                    {row.map((cell, cellIndex) => (
                      <td
                        key={`${table.spec.id}-${rowIndex}-${cellIndex}`}
                        className="px-2 py-1"
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-6 text-center text-[9pt] text-slate-500">
            Table preview unavailable.
          </div>
        )}
        <figcaption className="mt-2 text-center text-[9pt] text-slate-700">
          <span className="font-semibold">
            Table {toRoman(table.spec.table_number ?? 1)}.
          </span>{" "}
          {stripLeadingCaptionLabel(table.spec.caption)}
        </figcaption>
        {!hasTabularData && table.render_error ? (
          <p className="mt-1 text-center text-[8.5pt] text-rose-600">
            {table.render_error}
          </p>
        ) : null}
      </figure>
    );
  }

  function renderSectionVisuals(sectionId: RenderableSectionId) {
    return (
      <>
        {projectId
          ? (figuresBySection.get(sectionId) ?? []).map(renderUploadedFigure)
          : null}
        {(generatedFiguresBySection.get(sectionId) ?? []).map(
          renderGeneratedFigure,
        )}
        {(generatedTablesBySection.get(sectionId) ?? []).map(renderGeneratedTable)}
      </>
    );
  }

  return (
    <div className="rounded-[28px] border border-white/10 bg-white p-6 shadow-[0_24px_60px_rgba(0,0,0,0.28)] md:p-8">
      <div className="mx-auto max-w-[880px] text-black">
        <div
          className="space-y-4"
          style={{
            fontFamily: '"Times New Roman", Times, serif',
            fontSize: "10pt",
            lineHeight: 1.2,
          }}
        >
          <header className="space-y-3 text-center">
            <p className="text-[9pt] uppercase tracking-[0.32em] text-slate-500">
              IEEE Conference Preview
            </p>
            <h1
              className="text-balance font-semibold text-slate-950"
              style={{ fontSize: "24pt", lineHeight: 1.1 }}
            >
              {title.trim() || "Untitled Research Paper"}
            </h1>
            <div className="space-y-1 text-[11pt] text-slate-800">
              {authors.length > 0 ? (
                authors.map((author) => (
                  <p key={author}>{author}</p>
                ))
              ) : (
                <p>Author details pending.</p>
              )}
            </div>
          </header>

          <section className="space-y-2 border-y border-slate-200 py-4">
            <p className="text-justify">
              <span className="font-semibold">Abstract - </span>
              {preview.abstract}
            </p>
            <p className="text-justify">
              <span className="font-semibold">Index Terms - </span>
              {preview.keywords.length > 0
                ? preview.keywords.join(", ")
                : "keywords pending author input"}
            </p>
            {renderSectionVisuals("abstract")}
          </section>

          <div className="space-y-6 lg:columns-2 lg:gap-8 lg:space-y-0">
            {preview.sections.map((section) => (
              <section
                key={section.id}
                className="mb-6 break-inside-avoid-column space-y-3"
              >
                <h2 className="text-center text-[11pt] font-semibold tracking-[0.16em] text-slate-950 uppercase">
                  {section.heading}
                </h2>
                <div className="space-y-3 text-justify text-slate-900">
                  {splitParagraphs(section.content).map((paragraph, index) => (
                    <p
                      key={`${section.id}-${index}`}
                      className={index === 0 ? "" : "indent-[0.14in]"}
                    >
                      {paragraph}
                    </p>
                  ))}
                </div>
                {renderSectionVisuals(section.id)}
              </section>
            ))}

            <section className="mb-2 break-inside-avoid-column space-y-3">
              <h2 className="text-center text-[11pt] font-semibold tracking-[0.16em] text-slate-950 uppercase">
                REFERENCES
              </h2>
              <ol className="space-y-2 text-[9.5pt] text-slate-900">
                {preview.references.map((reference, index) => (
                  <li key={`${reference}-${index}`} className="text-justify">
                    {reference}
                  </li>
                ))}
              </ol>
            </section>

            {hasFallbackVisuals ? (
              <section className="mb-2 break-inside-avoid-column space-y-3">
                <h2 className="text-center text-[11pt] font-semibold tracking-[0.16em] text-slate-950 uppercase">
                  FIGURES AND TABLES
                </h2>
                <p className="text-center text-[9pt] text-slate-600">
                  These visuals could not be matched to the current preview
                  headings, so they are shown here instead.
                </p>
                {projectId ? unmatchedFigures.map(renderUploadedFigure) : null}
                {unmatchedGeneratedFigures.map(renderGeneratedFigure)}
                {unmatchedGeneratedTables.map(renderGeneratedTable)}
              </section>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function normalizeGeneratedTableRows(rows: unknown, columnCount: number) {
  if (!Array.isArray(rows)) {
    return [] as string[][];
  }

  return rows.map((row) => {
    const values = Array.isArray(row)
      ? row.map((value) => String(value))
      : [String(row)];

    if (columnCount > 0) {
      if (values.length < columnCount) {
        values.push(...Array.from({ length: columnCount - values.length }, () => ""));
      } else if (values.length > columnCount) {
        values.length = columnCount;
      }
    }

    return values;
  });
}

function toRoman(value: number) {
  const numerals: Array<[number, string]> = [
    [1000, "M"],
    [900, "CM"],
    [500, "D"],
    [400, "CD"],
    [100, "C"],
    [90, "XC"],
    [50, "L"],
    [40, "XL"],
    [10, "X"],
    [9, "IX"],
    [5, "V"],
    [4, "IV"],
    [1, "I"],
  ];

  let remaining = Math.max(1, Math.trunc(value));
  let output = "";

  for (const [arabic, roman] of numerals) {
    while (remaining >= arabic) {
      output += roman;
      remaining -= arabic;
    }
  }

  return output;
}

function stripLeadingCaptionLabel(value: string) {
  return value
    .replace(/^Fig\.\s*\d+\.\s*/i, "")
    .replace(/^Table\s+[IVXLCDM]+\.\s*/i, "")
    .trim();
}

function resolveSectionId(
  rawSection: string | undefined,
  preview: ParsedIeeeManuscript,
  placementHint?: string | null,
): RenderableSectionId | null {
  const normalizedSection = normalizeSectionToken(rawSection);
  if (normalizedSection) {
    const aliasedSection = SECTION_ALIAS_MAP[normalizedSection];
    if (aliasedSection) {
      return aliasedSection;
    }
  }

  const normalizedPlacementHint = normalizeSearchText(placementHint);
  if (normalizedPlacementHint) {
    if (normalizeSearchText(preview.abstract).includes(normalizedPlacementHint)) {
      return "abstract";
    }

    const matchedSection = preview.sections.find((section) =>
      normalizeSearchText(section.content).includes(normalizedPlacementHint),
    );
    if (matchedSection) {
      return matchedSection.id;
    }
  }

  return null;
}

function normalizeSectionToken(value: string | undefined) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/^[ivxlcdm]+\.\s*/i, "")
    .replace(/^(section|sec)\s+/i, "")
    .replace(/[_-]+/g, " ")
    .replace(/[&/]+/g, " and ")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeSearchText(value: string | null | undefined) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}
