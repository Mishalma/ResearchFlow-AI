import Link from "next/link";
import {
  ArrowRight,
  Bot,
  FileText,
  Network,
  Quote,
  Sparkles,
  UploadCloud,
} from "lucide-react";

import { FloatingCard } from "@/components/3d/FloatingCard";
import { BackendHealthStatus } from "@/components/shared/BackendHealthStatus";
import { Badge } from "@/components/ui/badge";

const workflowCards = [
  {
    title: "Upload Source",
    description:
      "Send a real PDF or DOCX file to the FastAPI backend for extraction.",
    icon: UploadCloud,
  },
  {
    title: "Generate Draft",
    description:
      "Run the multi-agent Vertex AI pipeline to produce paper sections and references.",
    icon: Bot,
  },
  {
    title: "Review Output",
    description:
      "Open the live editor view to inspect the generated paper and metadata.",
    icon: FileText,
  },
];

export default function Dashboard() {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 space-y-10 pb-10 duration-500">
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div className="space-y-5 pt-4 lg:col-span-2">
          <Badge className="border border-indigo-400/30 bg-indigo-500/15 text-indigo-100">
            ResearchFlow Live Demo
          </Badge>
          <h1 className="text-4xl font-bold tracking-tight text-white drop-shadow-[0_0_15px_rgba(255,255,255,0.2)] md:text-5xl">
            Generate research papers from real backend data.
          </h1>
          <p className="max-w-2xl text-lg leading-relaxed text-indigo-200/70">
            This frontend is now connected to the live FastAPI plus Vertex AI
            pipeline. Upload a source document, run generation, and review the
            actual result returned by the backend.
          </p>

          <div className="flex flex-wrap gap-3">
            <Link
              href="/new"
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-600/80 px-2.5 text-sm font-medium whitespace-nowrap text-white shadow-[0_0_15px_rgba(79,70,229,0.4)] transition-all hover:bg-indigo-500"
            >
              Start New Project <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
            <a
              href="http://127.0.0.1:8002/docs"
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-transparent px-2.5 text-sm font-medium whitespace-nowrap text-indigo-200 transition-all hover:bg-white/10"
            >
              Open Backend Docs
            </a>
          </div>
        </div>

        <FloatingCard className="lg:col-span-1">
          <div className="space-y-4 p-6">
            <h3 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
              <Sparkles className="h-4 w-4 text-indigo-400" />
              Connected Flow
            </h3>
            <div className="space-y-3 text-sm text-indigo-200/75">
              <p className="rounded-xl border border-white/10 bg-white/5 p-4">
                Frontend upload form uses the live `/upload` endpoint.
              </p>
              <p className="rounded-xl border border-white/10 bg-white/5 p-4">
                The processing screen calls the live `/generate` endpoint.
              </p>
              <p className="rounded-xl border border-white/10 bg-white/5 p-4">
                The editor reads the stored project from <code>/project/{"{id}"}</code>.
              </p>
            </div>
          </div>
        </FloatingCard>
      </div>

      <BackendHealthStatus />

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {workflowCards.map((card, index) => (
          <FloatingCard key={card.title} delay={index * 0.08}>
            <div className="h-full rounded-2xl border border-white/10 bg-black/30 p-6 backdrop-blur-xl">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-indigo-400/30 bg-indigo-500/15">
                <card.icon className="h-5 w-5 text-indigo-300" />
              </div>
              <h2 className="text-xl font-bold tracking-tight text-white">
                {card.title}
              </h2>
              <p className="mt-3 text-sm leading-6 text-indigo-200/70">
                {card.description}
              </p>
            </div>
          </FloatingCard>
        ))}
      </div>

      <FloatingCard>
        <div className="grid gap-6 rounded-2xl border border-white/10 bg-black/30 p-8 backdrop-blur-xl md:grid-cols-3">
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-white">
              <Network className="h-4 w-4 text-indigo-300" />
              <h3 className="font-semibold">FastAPI</h3>
            </div>
            <p className="text-sm leading-6 text-indigo-200/70">
              Handles upload, project storage, generation routing, and error
              handling.
            </p>
          </div>
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-white">
              <Sparkles className="h-4 w-4 text-indigo-300" />
              <h3 className="font-semibold">Vertex AI</h3>
            </div>
            <p className="text-sm leading-6 text-indigo-200/70">
              Gemini generates the structured paper through the multi-agent
              orchestration pipeline.
            </p>
          </div>
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-white">
              <Quote className="h-4 w-4 text-indigo-300" />
              <h3 className="font-semibold">MCP Tools</h3>
            </div>
            <p className="text-sm leading-6 text-indigo-200/70">
              Citation formatting and search are surfaced in the UI as part of
              the generated paper metadata.
            </p>
          </div>
        </div>
      </FloatingCard>
    </div>
  );
}
