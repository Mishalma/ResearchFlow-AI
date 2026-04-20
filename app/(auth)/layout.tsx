import type { ReactNode } from "react";
import { FileText, ShieldCheck, Sparkles } from "lucide-react";

import { PublicHomeFooter } from "@/components/marketing/home/public-home-footer";
import { PublicHomeNav } from "@/components/marketing/home/public-home-nav";
import { getServerSessionUser } from "@/lib/server/auth/session";

const authHighlights = [
  {
    title: "Private by default",
    description:
      "Session-backed access with a secure Cloud Run workspace and protected project data.",
    icon: ShieldCheck,
  },
  {
    title: "One editorial flow",
    description:
      "Draft, refine, cite, and export academic work without hopping between disconnected tools.",
    icon: Sparkles,
  },
  {
    title: "Format-ready output",
    description:
      "Preview and polish research papers before you export to PDF, DOCX, or LaTeX.",
    icon: FileText,
  },
];

export const dynamic = "force-dynamic";

export default async function AuthLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  const user = await getServerSessionUser();
  const ExportReadyIcon = authHighlights[2].icon;

  return (
    <div className="relative min-h-screen overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 overflow-hidden"
      >
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(79,70,229,0.18),transparent_38%),radial-gradient(circle_at_bottom_left,rgba(14,165,233,0.12),transparent_30%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(255,255,255,0.12)_1px,transparent_0)] [background-size:30px_30px] opacity-[0.08]" />
        <div className="absolute left-[8%] top-28 h-72 w-72 rounded-full bg-indigo-500/10 blur-[120px]" />
        <div className="absolute bottom-8 right-[8%] h-72 w-72 rounded-full bg-sky-500/10 blur-[120px]" />
      </div>

      <PublicHomeNav user={user} variant="auth" />

      <main className="relative px-4 pb-16 pt-8 md:px-6 lg:px-8">
        <div className="mx-auto grid min-h-[calc(100vh-13rem)] max-w-7xl items-center gap-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(440px,480px)] lg:gap-16">
          <section className="hidden lg:block">
            <div className="max-w-2xl space-y-8">
              <span className="inline-flex rounded-full border border-white/10 bg-white/6 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-[0.3em] text-indigo-100/78">
                Secure Editorial Workspace
              </span>

              <div className="space-y-5">
                <h1 className="text-5xl font-semibold tracking-tight text-white xl:text-6xl">
                  Enter the research workspace built for{" "}
                  <span className="bg-gradient-to-r from-indigo-200 via-indigo-300 to-sky-300 bg-clip-text text-transparent italic">
                    evidence-first writing
                  </span>
                  .
                </h1>
                <p className="max-w-xl text-lg leading-8 text-indigo-100/72">
                  PaperEasy helps you generate, refine, cite, and format
                  academic drafts from one focused, secure workflow.
                </p>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                {authHighlights.slice(0, 2).map((item) => (
                  <div
                    key={item.title}
                    className="rounded-[28px] border border-white/10 bg-black/20 p-5 backdrop-blur-xl"
                  >
                    <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/6 text-indigo-100">
                      <item.icon className="h-5 w-5" />
                    </div>
                    <h2 className="text-lg font-semibold tracking-tight text-white">
                      {item.title}
                    </h2>
                    <p className="mt-2 text-sm leading-7 text-indigo-100/68">
                      {item.description}
                    </p>
                  </div>
                ))}
              </div>

              <div className="rounded-[30px] border border-white/10 bg-black/25 p-6 backdrop-blur-xl">
                <div className="mb-4 flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/6 text-indigo-100">
                    <ExportReadyIcon className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="text-lg font-semibold tracking-tight text-white">
                      {authHighlights[2].title}
                    </p>
                    <p className="text-sm text-indigo-100/60">
                      Built for modern academic workflows.
                    </p>
                  </div>
                </div>
                <p className="max-w-xl text-sm leading-7 text-indigo-100/70">
                  {authHighlights[2].description}
                </p>
              </div>
            </div>
          </section>

          <div className="mx-auto w-full max-w-[480px] lg:justify-self-end">
            {children}
          </div>
        </div>
      </main>

      <PublicHomeFooter />
    </div>
  );
}
