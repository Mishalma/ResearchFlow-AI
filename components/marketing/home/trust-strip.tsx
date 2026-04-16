import {
  EyeOff,
  LockKeyhole,
  ShieldCheck,
  UserRoundCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

const trustItems = [
  {
    label: "Secure AI Workspace",
    icon: ShieldCheck,
  },
  {
    label: "Private Processing",
    icon: LockKeyhole,
  },
  {
    label: "No Data Leakage",
    icon: EyeOff,
  },
  {
    label: "User-Scoped Access",
    icon: UserRoundCheck,
  },
];

export function TrustStrip() {
  return (
    <section className="px-4 py-6 md:px-6 md:py-8 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <div className="rounded-[28px] border border-white/10 bg-[#0a1020]/80 p-2 shadow-[0_18px_60px_-42px_rgba(79,70,229,0.55)] backdrop-blur-2xl">
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {trustItems.map((item, index) => (
            <div
              key={item.label}
              className={cn(
                "relative flex items-center gap-3 rounded-[22px] bg-white/[0.03] px-4 py-4 text-sm text-indigo-100/82 transition-colors hover:bg-white/[0.05] md:px-5",
                index < trustItems.length - 1 &&
                  "after:pointer-events-none after:absolute after:right-0 after:top-1/2 after:hidden after:h-8 after:w-px after:-translate-y-1/2 after:bg-white/8 xl:after:block",
              )}
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-indigo-400/18 bg-gradient-to-br from-indigo-500/14 to-sky-400/10 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
                <item.icon className="h-4 w-4 text-indigo-300" />
              </div>
              <div className="min-w-0">
                <p className="font-medium tracking-tight text-white/92">
                  {item.label}
                </p>
                <p className="mt-1 text-xs text-indigo-200/48">
                  Protected research workflow
                </p>
              </div>
            </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
