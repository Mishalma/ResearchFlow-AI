import { Star } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { FloatingCard } from "@/components/3d/FloatingCard";

import { SectionHeading } from "./section-heading";

const testimonials = [
  {
    name: "Dr. Aris Thorne",
    role: "Senior Research Fellow",
    quote:
      "PaperEasy gave me a calmer, faster path from source material to submission-ready structure. The editor feels built for serious academic work.",
  },
  {
    name: "Sarah Jenkins",
    role: "PhD Candidate, Stanford",
    quote:
      "It is the first research writing tool I have used that feels trustworthy, secure, and simple enough to fit into my real workflow.",
  },
  {
    name: "Marcus Vane",
    role: "Lead Investigator",
    quote:
      "The combination of structured generation, refinement support, and export readiness saves hours on every draft cycle.",
  },
];

export function TestimonialsSection() {
  return (
    <section className="px-4 py-8 md:px-6 md:py-12 lg:px-8 lg:py-16">
      <div className="mx-auto max-w-7xl space-y-10">
        <SectionHeading
          eyebrow="Testimonials"
          title="What Our Users Say"
          description="Static for now, but tuned to the audience you are serving: academic writers who care about quality, trust, and speed."
        />

        <div className="grid gap-4 lg:grid-cols-3 lg:gap-6">
          {testimonials.map((testimonial, index) => (
            <FloatingCard
              key={testimonial.name}
              className="group"
              delay={index * 0.06}
            >
              <div className="h-full rounded-[28px] border border-white/10 bg-black/30 p-6 backdrop-blur-xl">
                <div className="mb-5 flex items-center gap-1 text-indigo-300">
                  {Array.from({ length: 5 }).map((_, starIndex) => (
                    <Star
                      key={starIndex}
                      className="h-4 w-4 fill-current text-indigo-300"
                    />
                  ))}
                </div>

                <p className="text-base leading-8 text-indigo-100/86">
                  “{testimonial.quote}”
                </p>

                <div className="mt-6 flex items-center gap-3">
                  <Avatar className="h-11 w-11 border border-indigo-400/20">
                    <AvatarFallback className="bg-indigo-950 text-sm font-bold text-indigo-100">
                      {testimonial.name
                        .split(/\s+/)
                        .map((part) => part[0])
                        .join("")
                        .slice(0, 2)}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <p className="font-semibold text-white">{testimonial.name}</p>
                    <p className="text-xs uppercase tracking-[0.22em] text-indigo-200/58">
                      {testimonial.role}
                    </p>
                  </div>
                </div>
              </div>
            </FloatingCard>
          ))}
        </div>
      </div>
    </section>
  );
}
