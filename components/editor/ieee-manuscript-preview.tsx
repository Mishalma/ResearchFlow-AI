import {
  buildFigureAssetUrl,
  type FigureRecord,
} from "@/lib/backend";
import type { ParsedIeeeManuscript } from "@/lib/ieee-manuscript";

type IeeeManuscriptPreviewProps = {
  title: string;
  authors: string[];
  preview: ParsedIeeeManuscript;
  figures?: FigureRecord[];
  projectId?: string | null;
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
  projectId,
}: IeeeManuscriptPreviewProps) {
  const figuresBySection = new Map<string, FigureRecord[]>();
  const figureNumberById = new Map<string, number>();

  figures.forEach((figure, index) => {
    figureNumberById.set(figure.id, index + 1);
    const bucket = figuresBySection.get(figure.section) ?? [];
    bucket.push(figure);
    figuresBySection.set(figure.section, bucket);
  });

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

                {projectId
                  ? (figuresBySection.get(section.id) ?? []).map((figure) => (
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
                    ))
                  : null}
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
          </div>
        </div>
      </div>
    </div>
  );
}
