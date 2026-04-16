import { Bot, FileOutput, Lightbulb, PenSquare } from "lucide-react";

import { FloatingCard } from "@/components/3d/FloatingCard";

import { SectionHeading } from "./section-heading";

const steps = [
  {
    title: "Input your topic",
    description:
      "Start with a paper idea, thesis, outline, or source material for the AI workspace to structure.",
    icon: Lightbulb,
  },
  {
    title: "AI generates structured paper",
    description:
      "Research flow drafts a complete academic paper structure with secure server-side generation.",
    icon: Bot,
  },
  {
    title: "Edit & refine in smart editor",
    description:
      "Polish language, tighten sections, and improve clarity inside a manuscript-first editor.",
    icon: PenSquare,
  },
  {
    title: "Export in IEEE / academic format",
    description:
      "Finalize your paper and prepare it for academic delivery with export-ready formatting.",
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
          title="How researchflow Works"
          description="A clean, guided workflow that moves from idea to polished manuscript without exposing your research to the public web."
        />

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 xl:gap-6">
          {steps.map((step, index) => (
            <FloatingCard key={step.title} className="group" delay={index * 0.05}>
              <div className="h-full rounded-[26px] border border-white/10 bg-black/30 p-5 backdrop-blur-xl md:p-6">
                <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl border border-indigo-400/20 bg-indigo-500/10">
                  <step.icon className="h-5 w-5 text-indigo-300" />
                </div>
                <h3 className="text-xl font-semibold tracking-tight text-white">
                  {step.title}
                </h3>
                <p className="mt-3 text-sm leading-7 text-indigo-200/68">
                  {step.description}
                </p>
              </div>
            </FloatingCard>
          ))}
        </div>
      </div>
    </section>
  );
}
