import { Sparkles } from "lucide-react";

import { FloatingCard } from "@/components/3d/FloatingCard";

import { DashboardMockup } from "./dashboard-mockup";
import { SectionHeading } from "./section-heading";

export function DashboardPreviewSection() {
  return (
    <section className="px-4 py-8 md:px-6 md:py-12 lg:px-8 lg:py-16">
      <div className="mx-auto max-w-7xl space-y-10">
        <SectionHeading
          eyebrow="Product Preview"
          title="A high-trust editorial dashboard built for academic work"
          description="See the workspace before you sign in: focused editing on the left, manuscript intelligence in the center, and AI assistance on the right."
        />

        <FloatingCard className="group">
          <div className="grid gap-8 rounded-[30px] border border-white/10 bg-black/30 p-5 backdrop-blur-2xl md:p-6 lg:grid-cols-[300px_minmax(0,1fr)]">
            <div className="space-y-5 rounded-[26px] border border-white/10 bg-white/5 p-5">
              <div className="inline-flex items-center gap-2 rounded-full border border-indigo-400/20 bg-indigo-500/10 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.24em] text-indigo-200/90">
                <Sparkles className="h-3.5 w-3.5 text-indigo-300" />
                Research Workspace
              </div>

              <h3 className="text-2xl font-semibold tracking-tight text-white">
                Review full papers without leaving the secure editor.
              </h3>

              <p className="text-sm leading-7 text-indigo-200/70">
                The same interface supports structured drafting, suggestions,
                figure handling, and export preparation while keeping users on
                the safe side of your private backend.
              </p>

              <div className="grid gap-3">
                {[
                  "Focused manuscript canvas",
                  "Saved projects in one place",
                  "AI suggestion rail for refinement",
                ].map((item) => (
                  <div
                    key={item}
                    className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-100"
                  >
                    {item}
                  </div>
                ))}
              </div>
            </div>

            <DashboardMockup variant="showcase" />
          </div>
        </FloatingCard>
      </div>
    </section>
  );
}
