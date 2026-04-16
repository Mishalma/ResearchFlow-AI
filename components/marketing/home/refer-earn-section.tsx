import Link from "next/link";
import { ArrowRight, Gift, Users } from "lucide-react";

import type { AuthenticatedUser } from "@/lib/server/auth/session";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";

type ReferEarnSectionProps = {
  user: AuthenticatedUser | null;
};

function getReferHref(user: AuthenticatedUser | null) {
  return user ? "/editor" : "/login?next=%2Feditor";
}

export function ReferEarnSection({ user }: ReferEarnSectionProps) {
  return (
    <section
      id="refer-earn"
      className="scroll-mt-28 px-4 py-8 md:px-6 md:py-12 lg:px-8 lg:py-16"
    >
      <div className="mx-auto max-w-5xl rounded-[34px] border border-indigo-400/15 bg-gradient-to-br from-[#2b3270]/88 via-[#242a57]/92 to-[#181d39]/96 p-8 text-center shadow-[0_35px_90px_-50px_rgba(129,140,248,0.85)] backdrop-blur-2xl md:p-10 lg:p-14">
        <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.24em] text-indigo-100/85">
          <Gift className="h-4 w-4 text-indigo-200" />
          Refer & Earn
        </div>

        <h2 className="mt-6 text-4xl font-bold tracking-tight text-white md:text-5xl">
          Invite friends and grow your academic toolkit together.
        </h2>
        <p className="mx-auto mt-4 max-w-2xl text-lg leading-8 text-indigo-100/72">
          Share PaperEasy with researchers, students, and academic teams. Earn
          rewards when your network joins the workspace and starts publishing
          smarter.
        </p>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-3 text-sm text-indigo-100/78">
          <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2">
            <Users className="h-4 w-4 text-indigo-200" />
            Invite peers
          </div>
          <div className="rounded-full border border-white/10 bg-white/10 px-4 py-2">
            Unlock rewards
          </div>
          <div className="rounded-full border border-white/10 bg-white/10 px-4 py-2">
            Expand editorial access
          </div>
        </div>

        <Link
          href={getReferHref(user)}
          className={cn(
            buttonVariants({ size: "lg" }),
            "mx-auto mt-8 h-12 rounded-2xl border border-indigo-200/35 bg-indigo-200/90 px-7 text-[#1b2250] shadow-[0_0_22px_rgba(165,180,252,0.4)] hover:bg-white",
          )}
        >
          Invite Friends & Earn Rewards
          <ArrowRight className="ml-2 h-4 w-4" />
        </Link>
      </div>
    </section>
  );
}
