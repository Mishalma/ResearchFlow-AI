import {
  EyeOff,
  LockKeyhole,
  ShieldCheck,
  UserRoundCheck,
} from "lucide-react";

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
    <section className="px-4 py-8 md:px-6 md:py-10 lg:px-8">
      <div className="mx-auto max-w-7xl rounded-[28px] border border-white/10 bg-black/30 backdrop-blur-2xl">
        <div className="grid gap-px rounded-[28px] bg-white/5 sm:grid-cols-2 xl:grid-cols-4">
          {trustItems.map((item) => (
            <div
              key={item.label}
              className="flex items-center gap-3 rounded-[28px] bg-[#090f1d]/82 px-5 py-4 text-sm text-indigo-100/82"
            >
              <div className="rounded-2xl border border-indigo-400/20 bg-indigo-500/10 p-2.5">
                <item.icon className="h-4 w-4 text-indigo-300" />
              </div>
              <span className="font-medium">{item.label}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
