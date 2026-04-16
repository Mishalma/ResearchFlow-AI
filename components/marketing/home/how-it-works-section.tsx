import {
  Bot,
  FileOutput,
  Lightbulb,
  PenSquare,
} from "lucide-react";

import { FloatingCard } from "@/components/3d/FloatingCard";

import { SectionHeading } from "./section-heading";

const steps = [
  {
    step: "01",
    title: "Input Topic & Sources",
    description:
      "Start with your topic, abstract, notes, or source documents so the workspace has the right research context.",
    icon: Lightbulb,
  },
  {
    step: "02",
    title: "Agents Generate Outline & Draft",
    description:
      "Specialized AI agents coordinate structure, section drafting, and academic flow to build a stronger first version.",
    icon: Bot,
  },
  {
    step: "03",
    title: "Refine in Smart Editor",
    description:
      "Edit with plagiarism-aware cleanup and AI-detection-friendly language polishing while preserving meaning.",
    icon: PenSquare,
  },
  {
    step: "04",
    title: "Export in IEEE Format",
    description:
      "Finalize citations, figures, and layout, then export your manuscript in IEEE-ready academic formats.",
    icon: FileOutput,
  },
];

export function HowItWorksSection() {
  return (
    <section
      id="how-it-works"
      className="scroll-mt-28 px-4 py-8 md:px-6 md:py-12 lg:px-8 lg:py-16"
    >
      <div className="mx-auto max-w-7xl space-y-10">
        <SectionHeading
          eyebrow="Guided Workflow"
          title="How It Works"
          description="A secure academic flow that starts with your research inputs, uses coordinated AI agents for drafting, and finishes with cleaner, submission-ready output."
        />

        <div className="relative">
          <div className="pointer-events-none absolute left-[8%] right-[8%] top-[92px] hidden h-px bg-gradient-to-r from-transparent via-sky-400/65 to-transparent xl:block" />
          <div className="pointer-events-none absolute left-[12%] right-[12%] top-[88px] hidden h-3 rounded-full bg-sky-400/12 blur-xl xl:block" />

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 xl:gap-6">
          {steps.map((step, index) => (
            <FloatingCard key={step.title} className="group" delay={index * 0.05}>
              <div className="relative h-full overflow-hidden rounded-[28px] border border-sky-300/14 bg-gradient-to-b from-[#111a2c]/96 via-[#0c1323]/94 to-[#151024]/94 p-5 shadow-[0_20px_60px_-35px_rgba(56,189,248,0.28)] backdrop-blur-xl md:p-6">
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-fuchsia-400/10 via-indigo-400/4 to-transparent" />
                <div className="relative">
                  <div className="mb-5 flex items-start justify-between gap-3">
                    <div className="flex h-11 min-w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/6 text-sm font-semibold text-white/92">
                      {step.step}
                    </div>
                    <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-indigo-400/20 bg-indigo-500/10">
                      <step.icon className="h-5 w-5 text-indigo-300" />
                    </div>
                  </div>

                  <h3 className="max-w-[14rem] text-[1.65rem] font-semibold leading-tight tracking-tight text-white">
                    {step.title}
                  </h3>
                  <p className="mt-4 text-sm leading-7 text-indigo-200/68">
                    {step.description}
                  </p>
                </div>
              </div>
            </FloatingCard>
          ))}
          </div>
        </div>
      </div>
    </section>
  );
}
