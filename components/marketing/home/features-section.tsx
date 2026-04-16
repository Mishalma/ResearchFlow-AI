import { FolderOpen, PenSquare, ScanSearch, ShieldAlert } from "lucide-react";

import { FloatingCard } from "@/components/3d/FloatingCard";

import { SectionHeading } from "./section-heading";

const features = [
  {
    title: "Smart Editor",
    description:
      "Work inside a manuscript-first editing space built for structured academic writing and revisions.",
    icon: PenSquare,
  },
  {
    title: "Project Management",
    description:
      "Keep research drafts, figures, and paper revisions organized inside one secure workspace.",
    icon: FolderOpen,
  },
  {
    title: "Plagiarism Remover",
    description:
      "Refine overlap-heavy passages and prepare cleaner submission-ready academic content.",
    icon: ShieldAlert,
  },
  {
    title: "AI Detection Remover",
    description:
      "Humanize tone and improve editorial flow while maintaining research intent and clarity.",
    icon: ScanSearch,
  },
];

export function FeaturesSection() {
  return (
    <section
      id="features"
      className="scroll-mt-28 px-4 py-8 md:px-6 md:py-12 lg:px-8 lg:py-16"
    >
      <div className="mx-auto max-w-7xl space-y-10">
        <SectionHeading
          eyebrow="Core Features"
          title="Built for scholars who need confidence, speed, and control"
          description="Every core workflow sits inside the same secure interface, from drafting to refinement to academic export."
        />

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 xl:gap-6">
          {features.map((feature, index) => (
            <FloatingCard
              key={feature.title}
              className="group"
              delay={index * 0.05}
            >
              <div className="h-full rounded-[26px] border border-white/10 bg-gradient-to-br from-black/35 via-[#0b1020]/85 to-black/35 p-5 backdrop-blur-xl md:p-6">
                <div className="mb-5 inline-flex rounded-2xl border border-indigo-400/20 bg-indigo-500/10 p-3">
                  <feature.icon className="h-5 w-5 text-indigo-300" />
                </div>
                <h3 className="text-xl font-semibold tracking-tight text-white">
                  {feature.title}
                </h3>
                <p className="mt-3 text-sm leading-7 text-indigo-200/68">
                  {feature.description}
                </p>
              </div>
            </FloatingCard>
          ))}
        </div>
      </div>
    </section>
  );
}
