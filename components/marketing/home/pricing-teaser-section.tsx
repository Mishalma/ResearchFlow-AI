import Link from "next/link";
import { ArrowRight, Coins, ShieldCheck } from "lucide-react";

import type { AuthenticatedUser } from "@/lib/server/auth/session";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";

import { SectionHeading } from "./section-heading";

type PricingTeaserSectionProps = {
  user: AuthenticatedUser | null;
};

function getPricingCtaHref(user: AuthenticatedUser | null) {
  return user ? "/new" : "/login?next=%2Fnew";
}

export function PricingTeaserSection({
  user,
}: PricingTeaserSectionProps) {
  return (
    <section
      id="pricing"
      className="scroll-mt-28 px-4 py-8 md:px-6 md:py-12 lg:px-8 lg:py-16"
    >
      <div className="mx-auto max-w-7xl rounded-[30px] border border-white/10 bg-gradient-to-br from-[#0a1022]/90 via-[#111938]/88 to-[#080d18]/92 p-6 shadow-[0_25px_70px_-45px_rgba(79,70,229,0.6)] backdrop-blur-2xl md:p-8">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-center">
          <SectionHeading
            eyebrow="Pricing"
            align="left"
            title="Simple access to a secure academic writing workspace"
            description="Start quickly, draft papers faster, and keep your research workflow inside a private AI-assisted environment."
          />

          <div className="grid gap-4">
            <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
              <div className="flex items-center gap-2 text-white">
                <Coins className="h-4 w-4 text-indigo-300" />
                <p className="text-sm font-semibold uppercase tracking-[0.24em] text-indigo-200/80">
                  Pricing Preview
                </p>
              </div>
              <p className="mt-3 text-3xl font-bold text-white">
                Flexible plans for students, researchers, and teams
              </p>
              <p className="mt-3 text-sm leading-7 text-indigo-200/70">
                Move from idea to export-ready manuscript with one clean
                workspace and private processing built in.
              </p>
            </div>

            <div className="rounded-[24px] border border-indigo-400/15 bg-indigo-500/10 p-5">
              <div className="flex items-center gap-2 text-indigo-100">
                <ShieldCheck className="h-4 w-4 text-indigo-300" />
                <span className="text-sm font-medium">
                  Secure by default, built for real research workflows
                </span>
              </div>
            </div>

            <Link
              href={getPricingCtaHref(user)}
              className={cn(
                buttonVariants({ size: "lg" }),
                "h-12 rounded-2xl border border-indigo-400/30 bg-indigo-600/80 text-white hover:bg-indigo-500",
              )}
            >
              Get Started
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
