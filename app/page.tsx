import { FloatingCard } from "@/components/3d/FloatingCard";
import { BackendHealthStatus } from "@/components/shared/BackendHealthStatus";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  BarChart2,
  Download,
  FileText,
  Plus,
  Sparkles,
  UploadCloud,
  Users,
} from "lucide-react";
import Link from "next/link";

export default function Dashboard() {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 space-y-10 pb-10 duration-500">
      {/* Welcome & Quick Upload Section */}
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div className="space-y-4 pt-4 lg:col-span-2">
          <h1 className="text-4xl font-bold tracking-tight text-white drop-shadow-[0_0_15px_rgba(255,255,255,0.2)] md:text-5xl">
            Welcome back,{" "}
            <span className="font-serif font-normal italic text-indigo-300">
              Dr. Jenkins.
            </span>
          </h1>
          <p className="max-w-2xl text-lg leading-relaxed text-indigo-200/70">
            Your last session focused on{" "}
            <span className="font-semibold text-white">Pedagogy & AI</span>.
            Two reviews have been returned from the editorial board of Nature
            Machine Intelligence.
          </p>
        </div>

        <FloatingCard className="lg:col-span-1">
          <div className="p-6">
            <h3 className="mb-2 flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
              <Sparkles className="h-4 w-4 text-indigo-400" /> Quick Upload
            </h3>
            <p className="mb-4 text-sm text-indigo-300/70">
              Drag and drop any research PDF to extract citations immediately.
            </p>
            <div className="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-indigo-500/30 bg-white/5 p-6 text-center transition-all hover:border-indigo-400 hover:bg-indigo-500/10 hover:shadow-[0_0_20px_rgba(79,70,229,0.3)]">
              <UploadCloud className="mb-2 h-6 w-6 text-indigo-400" />
              <span className="text-xs font-semibold tracking-wider text-indigo-200">
                DROP FILE HERE
              </span>
            </div>
          </div>
        </FloatingCard>
      </div>

      <BackendHealthStatus />

      {/* My Papers Section */}
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-white">
              My Papers
            </h2>
            <p className="mt-1 text-sm text-indigo-300/70">
              Active research manuscripts and grant proposals.
            </p>
          </div>
          <Link
            href="/papers"
            className="flex items-center text-sm font-semibold text-indigo-400 transition-all hover:text-indigo-300 hover:drop-shadow-[0_0_8px_rgba(129,140,248,0.5)]"
          >
            View All Papers <ArrowRight className="ml-1 h-4 w-4" />
          </Link>
        </div>

        <div className="space-y-4">
          {/* Card 1 */}
          <FloatingCard delay={0.1}>
            <div className="flex flex-col items-start justify-between gap-6 p-6 md:flex-row md:items-center">
              <div className="flex items-center gap-5">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-indigo-500/30 bg-indigo-500/10 shadow-[0_0_10px_rgba(79,70,229,0.2)]">
                  <FileText className="h-6 w-6 text-indigo-400" />
                </div>
                <div>
                  <h3 className="mb-2 text-lg font-bold leading-none text-white">
                    Impact of AI on Modern Pedagogy
                  </h3>
                  <div className="flex flex-wrap items-center gap-3 text-xs font-medium text-indigo-200/70">
                    <span className="flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]"></span>
                      Draft
                    </span>
                    <span>Edited 2h ago</span>
                    <span className="flex items-center gap-1 text-white/50">
                      <Users className="h-3.5 w-3.5" /> 3 collaborators
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex w-full items-center gap-3 md:w-auto">
                <Button
                  variant="outline"
                  className="w-full border-white/10 bg-transparent text-xs font-bold tracking-wider text-indigo-200 hover:bg-white/10 md:w-auto"
                >
                  <Download className="mr-2 h-3.5 w-3.5" /> EXPORT
                </Button>
                <Button className="w-full border border-white/10 bg-white/10 text-white shadow-[0_0_15px_rgba(255,255,255,0.05)] hover:bg-white/20 md:w-auto">
                  Continue Writing
                </Button>
              </div>
            </div>
          </FloatingCard>

          {/* Card 2 */}
          <FloatingCard delay={0.2}>
            <div className="flex flex-col items-start justify-between gap-6 p-6 md:flex-row md:items-center">
              <div className="flex items-center gap-5">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-indigo-500/30 bg-indigo-500/10 shadow-[0_0_10px_rgba(79,70,229,0.2)]">
                  <BarChart2 className="h-6 w-6 text-indigo-400" />
                </div>
                <div>
                  <h3 className="mb-2 text-lg font-bold leading-none text-white">
                    Machine Learning in Climate Models
                  </h3>
                  <div className="flex flex-wrap items-center gap-3 text-xs font-medium text-indigo-200/70">
                    <span className="flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]"></span>
                      Ready
                    </span>
                    <span>Edited Oct 14, 2024</span>
                    <Badge
                      variant="secondary"
                      className="gap-1 rounded-md border border-indigo-500/30 bg-indigo-500/20 py-0 font-semibold text-indigo-300 shadow-[0_0_10px_rgba(79,70,229,0.2)] hover:bg-indigo-500/30"
                    >
                      <Sparkles className="h-3 w-3" /> AI Optimized
                    </Badge>
                  </div>
                </div>
              </div>
              <div className="flex w-full items-center gap-3 md:w-auto">
                <Button
                  variant="outline"
                  className="w-full border-white/10 bg-transparent text-xs font-bold tracking-wider text-indigo-200 hover:bg-white/10 md:w-auto"
                >
                  <Download className="mr-2 h-3.5 w-3.5" /> EXPORT
                </Button>
                <Button className="w-full border border-indigo-400/30 bg-indigo-600/80 text-white shadow-[0_0_15px_rgba(79,70,229,0.4)] hover:bg-indigo-500 md:w-auto">
                  View Final
                </Button>
              </div>
            </div>
          </FloatingCard>
        </div>
      </div>

      {/* Bottom Alerts / Projects */}
      <div className="grid grid-cols-1 gap-6 pt-4 md:grid-cols-3">
        <FloatingCard className="group relative cursor-pointer transition-colors delay-300 md:col-span-2">
          <div className="relative z-10 bg-indigo-900/30 p-8 backdrop-blur-md">
            <Badge className="mb-4 border border-indigo-500/30 bg-indigo-500/20 text-indigo-200 backdrop-blur-sm hover:bg-indigo-500/30">
              RESEARCH PULSE AI
            </Badge>
            <h3 className="mb-3 text-3xl font-bold tracking-tight text-white drop-shadow-[0_0_10px_rgba(255,255,255,0.3)]">
              Semantic overlap detected in 4 drafts.
            </h3>
            <p className="max-w-lg text-sm leading-relaxed text-indigo-200">
              Your recent paper on Climate Models shares key terminology with
              the Pedagogy draft. Would you like to merge citations or check for
              consistency?
            </p>
          </div>
          <div className="absolute top-0 right-0 h-64 w-64 translate-x-1/4 -translate-y-1/4 rounded-full bg-indigo-500 opacity-20 blur-[80px]" />
        </FloatingCard>

        <FloatingCard
          delay={0.4}
          className="group flex cursor-pointer flex-col items-center justify-center text-center"
        >
          <div className="flex h-full flex-col items-center justify-center bg-white/5 p-8 backdrop-blur-md">
            <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-full border border-indigo-400/30 bg-indigo-500/20 shadow-[0_0_15px_rgba(79,70,229,0.5)] transition-transform group-hover:scale-105">
              <Plus className="h-6 w-6 text-indigo-300 drop-shadow-[0_0_8px_rgba(165,180,252,0.8)]" />
            </div>
            <h3 className="mb-2 text-xl font-bold text-white drop-shadow-[0_0_5px_rgba(255,255,255,0.2)]">
              New Project
            </h3>
            <p className="px-4 text-sm font-medium text-indigo-200/70">
              Start a fresh manuscript, systematic review, or literature
              mapping.
            </p>
          </div>
        </FloatingCard>
      </div>
    </div>
  );
}
