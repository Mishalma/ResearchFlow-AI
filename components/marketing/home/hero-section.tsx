import Link from "next/link";
import { ArrowRight, CheckCircle2, ShieldCheck } from "lucide-react";

import type { AuthenticatedUser } from "@/lib/server/auth/session";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FloatingCard } from "@/components/3d/FloatingCard";

import { DashboardMockup } from "./dashboard-mockup";

type HeroSectionProps = {
  user: AuthenticatedUser | null;
};

function getStartedHref(user: AuthenticatedUser | null) {
  return user ? "/new" : "/login?next=%2Fnew";
}

function getLoginHref(user: AuthenticatedUser | null) {
  return user ? "/editor" : "/login";
}

export function HeroSection({ user }: HeroSectionProps) {
  return (
    <section
      id="hero"
      className="scroll-mt-28 px-4 pt-8 md:px-6 md:pt-10 lg:px-8 lg:pt-14"
    >
      <div className="mx-auto grid max-w-7xl gap-10 lg:grid-cols-[minmax(0,1fr)_1.06fr] lg:items-center">
        <div className="space-y-8">
          <div className="space-y-5">
            <Badge className="border border-indigo-400/25 bg-indigo-500/10 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.28em] text-indigo-100">
              <ShieldCheck className="mr-1.5 h-3.5 w-3.5 text-indigo-300" />
              Secure Editorial Intelligence
            </Badge>

            <h1 className="max-w-3xl text-5xl font-bold tracking-tight text-white md:text-6xl xl:text-7xl">
              Write Research Papers{" "}
              <span className="bg-gradient-to-r from-indigo-200 via-indigo-300 to-sky-300 bg-clip-text text-transparent italic">
                Effortlessly
              </span>{" "}
              with AI
            </h1>

            <p className="max-w-2xl text-lg leading-8 text-indigo-200/72 md:text-xl">
              Generate, edit, and format academic papers in minutes with a
              secure AI workspace.
            </p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row">
            <Link
              href={getStartedHref(user)}
              className={cn(
                buttonVariants({ size: "lg" }),
                "h-12 rounded-2xl border border-indigo-400/30 bg-indigo-600/85 px-6 text-white shadow-[0_0_24px_rgba(79,70,229,0.42)] hover:bg-indigo-500",
              )}
            >
              Get Started
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>

            <Link
              href={getLoginHref(user)}
              className={cn(
                buttonVariants({ variant: "outline", size: "lg" }),
                "h-12 rounded-2xl border border-white/10 bg-white/5 px-6 text-white hover:bg-white/10",
              )}
            >
              Login
            </Link>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[
              "Private Cloud Run processing",
              "Structured IEEE-ready drafting",
              "Ownership-scoped project access",
            ].map((item) => (
              <div
                key={item}
                className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-indigo-100/82 backdrop-blur-xl"
              >
                <CheckCircle2 className="h-4 w-4 text-emerald-300" />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>

        <FloatingCard className="group">
          <div className="rounded-[30px] border border-white/10 bg-black/20 p-3 backdrop-blur-2xl md:p-4">
            <DashboardMockup variant="hero" />
          </div>
        </FloatingCard>
      </div>
    </section>
  );
}
