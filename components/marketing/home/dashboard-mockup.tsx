import {
  Bot,
  CheckCircle2,
  LayoutPanelLeft,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { cn } from "@/lib/utils";

type DashboardMockupProps = {
  variant?: "hero" | "showcase";
};

const documentSections = [
  "Abstract",
  "Introduction",
  "Related Work",
  "Methodology",
  "Results",
  "Conclusion",
];

export function DashboardMockup({
  variant = "hero",
}: DashboardMockupProps) {
  const isShowcase = variant === "showcase";

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-[28px] border border-white/10 bg-[#060b1b]/85 shadow-[0_30px_90px_-40px_rgba(79,70,229,0.75)] backdrop-blur-2xl",
        isShowcase ? "p-4 md:p-5" : "p-3 md:p-4",
      )}
    >
      <div className="absolute inset-x-10 top-0 h-24 rounded-full bg-indigo-500/10 blur-3xl" />
      <div className="absolute -right-16 top-16 h-40 w-40 rounded-full bg-sky-400/10 blur-3xl" />

      <div className="relative rounded-[24px] border border-white/10 bg-black/35 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3 md:px-5">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-[#ff6b6b]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#f7b731]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#2ed573]" />
          </div>

          <div className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 md:flex">
            <Search className="h-3.5 w-3.5 text-zinc-400" />
            <span className="text-xs text-zinc-400">
              Search projects and research notes
            </span>
          </div>

          <div className="flex items-center gap-2 rounded-full border border-indigo-400/20 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-200">
            <ShieldCheck className="h-3.5 w-3.5" />
            Secure
          </div>
        </div>

        <div
          className={cn(
            "grid gap-3 p-3 md:gap-4 md:p-4",
            isShowcase
              ? "lg:grid-cols-[108px_minmax(0,1fr)_280px]"
              : "lg:grid-cols-[90px_minmax(0,1fr)_220px]",
          )}
        >
          <div className="rounded-[20px] border border-white/10 bg-white/5 p-3">
            <div className="flex items-center gap-2 rounded-xl border border-indigo-400/20 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-100">
              <LayoutPanelLeft className="h-3.5 w-3.5" />
              Panel
            </div>
            <div className="mt-4 space-y-2">
              {["Editor", "Projects", "Figures", "Exports"].map((item, index) => (
                <div
                  key={item}
                  className={cn(
                    "rounded-xl px-3 py-2 text-xs font-medium",
                    index === 0
                      ? "border border-indigo-400/20 bg-indigo-500/12 text-indigo-100"
                      : "bg-white/5 text-zinc-400",
                  )}
                >
                  {item}
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[22px] border border-white/10 bg-[#0a1122]/80 p-4 md:p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-300/70">
                  Paper Editor
                </p>
                <h3 className="mt-1 text-lg font-semibold text-white md:text-xl">
                  Generative Research Workflow
                </h3>
              </div>
              <div className="rounded-full border border-emerald-400/20 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-200">
                Draft synced
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-[180px_minmax(0,1fr)]">
              <div className="rounded-[18px] border border-white/10 bg-white/5 p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-zinc-400">
                  Outline
                </p>
                <div className="mt-3 space-y-2.5">
                  {documentSections.map((section, index) => (
                    <div
                      key={section}
                      className={cn(
                        "rounded-xl px-3 py-2 text-xs",
                        index === 2
                          ? "border border-indigo-400/20 bg-indigo-500/12 text-indigo-100"
                          : "bg-black/20 text-zinc-400",
                      )}
                    >
                      {section}
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-[18px] border border-white/10 bg-black/20 p-4">
                <div className="flex items-center gap-2 text-sm text-indigo-100">
                  <Sparkles className="h-4 w-4 text-indigo-300" />
                  AI-assisted manuscript
                </div>

                <div className="mt-4 space-y-3">
                  <div className="h-3 w-2/3 rounded-full bg-white/10" />
                  <div className="h-2 w-full rounded-full bg-white/6" />
                  <div className="h-2 w-11/12 rounded-full bg-white/6" />
                  <div className="h-2 w-10/12 rounded-full bg-white/6" />
                </div>

                <div className="mt-5 rounded-[18px] border border-indigo-400/15 bg-gradient-to-br from-indigo-500/10 via-transparent to-sky-400/10 p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-200/80">
                      Suggestion
                    </span>
                    <span className="rounded-full bg-white/10 px-2 py-1 text-[11px] text-indigo-100">
                      Tone match 96%
                    </span>
                  </div>

                  <div className="mt-3 space-y-2 text-sm text-zinc-200/88">
                    <p>
                      Refine the related work transition to strengthen the link
                      between cited evidence and your methodology rationale.
                    </p>
                    <div className="flex items-center gap-2 text-emerald-200">
                      <CheckCircle2 className="h-4 w-4" />
                      Ready to insert into the paper
                    </div>
                  </div>
                </div>

                <div className="mt-5 space-y-2">
                  <div className="h-2 w-full rounded-full bg-white/6" />
                  <div className="h-2 w-5/6 rounded-full bg-white/6" />
                  <div className="h-2 w-4/6 rounded-full bg-white/6" />
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-[22px] border border-white/10 bg-white/5 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <Bot className="h-4 w-4 text-indigo-300" />
              AI Suggestions
            </div>
            <p className="mt-1 text-sm leading-6 text-indigo-200/68">
              Private model guidance, structure checks, and export readiness.
            </p>

            <div className="mt-4 space-y-3">
              {[
                "Strengthen the abstract opening with the paper contribution.",
                "Standardize related-work citations before final export.",
                "Results section can benefit from a clearer evidence statement.",
              ].map((item) => (
                <div
                  key={item}
                  className="rounded-[18px] border border-white/10 bg-black/20 p-3"
                >
                  <p className="text-sm leading-6 text-zinc-200/82">{item}</p>
                </div>
              ))}
            </div>

            <div className="mt-4 rounded-[18px] border border-indigo-400/20 bg-indigo-500/10 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-200/80">
                Export Status
              </p>
              <p className="mt-2 text-sm text-zinc-100">
                IEEE formatting checks passed and manuscript is ready for final
                review.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
