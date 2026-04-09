import Link from "next/link";
import {
  ArrowRight,
  Bot,
  FileText,
  Lock,
  ShieldCheck,
  UploadCloud,
} from "lucide-react";

import { FloatingCard } from "@/components/3d/FloatingCard";
import { Badge } from "@/components/ui/badge";
import { getServerSessionUser } from "@/lib/server/auth/session";

const workflowCards = [
  {
    title: "Upload Source",
    description:
      "Securely upload a PDF or DOCX file through the Next.js backend-for-frontend layer.",
    icon: UploadCloud,
  },
  {
    title: "Generate Draft",
    description:
      "Run the authenticated multi-agent Vertex AI pipeline on your private Cloud Run backend.",
    icon: Bot,
  },
  {
    title: "Edit And Export",
    description:
      "Review the generated IEEE paper, save revisions, attach figures, and export final outputs.",
    icon: FileText,
  },
];

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const user = await getServerSessionUser();

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 space-y-10 px-4 pb-12 pt-6 duration-500 md:px-8">
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div className="space-y-5 pt-4 lg:col-span-2">
          <Badge className="border border-indigo-400/30 bg-indigo-500/15 text-indigo-100">
            Private Cloud Run + Vercel BFF
          </Badge>
          <h1 className="text-4xl font-bold tracking-tight text-white drop-shadow-[0_0_15px_rgba(255,255,255,0.2)] md:text-5xl">
            Generate, edit, and deliver research papers in a secure workspace.
          </h1>
          <p className="max-w-2xl text-lg leading-relaxed text-indigo-200/70">
            PaperEasy keeps the browser on the safe side of the boundary. Users work through
            authenticated Next.js routes, while the private FastAPI backend stays hidden on Cloud Run.
          </p>

          <div className="flex flex-wrap gap-3">
            <Link
              href={user ? "/new" : "/login"}
              className="inline-flex h-10 items-center justify-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-600/80 px-4 text-sm font-medium text-white shadow-[0_0_15px_rgba(79,70,229,0.4)] transition-all hover:bg-indigo-500"
            >
              {user ? "Open Workspace" : "Sign In To Start"}
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
            {!user ? (
              <Link
                href="/login"
                className="inline-flex h-10 items-center justify-center rounded-lg border border-white/10 bg-transparent px-4 text-sm font-medium text-indigo-200 transition-all hover:bg-white/10"
              >
                Create Account
              </Link>
            ) : null}
          </div>
        </div>

        <FloatingCard className="lg:col-span-1">
          <div className="space-y-4 p-6">
            <h3 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
              <ShieldCheck className="h-4 w-4 text-indigo-400" />
              Security Boundary
            </h3>
            <div className="space-y-3 text-sm text-indigo-200/75">
              <p className="rounded-xl border border-white/10 bg-white/5 p-4">
                Firebase Authentication protects user access and session state.
              </p>
              <p className="rounded-xl border border-white/10 bg-white/5 p-4">
                Next.js API routes proxy only the allowed backend operations.
              </p>
              <p className="rounded-xl border border-white/10 bg-white/5 p-4">
                Private Cloud Run receives trusted user headers only from the server.
              </p>
            </div>
          </div>
        </FloatingCard>
      </div>

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
              <Lock className="h-4 w-4 text-indigo-300" />
              <h3 className="font-semibold">Authenticated Sessions</h3>
            </div>
            <p className="text-sm leading-6 text-indigo-200/70">
              Server-managed cookies keep the browser session secure without exposing cloud credentials.
            </p>
          </div>
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-white">
              <Bot className="h-4 w-4 text-indigo-300" />
              <h3 className="font-semibold">Vertex AI Pipeline</h3>
            </div>
            <p className="text-sm leading-6 text-indigo-200/70">
              Gemini and the multi-agent orchestrator generate structured IEEE-ready papers.
            </p>
          </div>
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-white">
              <ShieldCheck className="h-4 w-4 text-indigo-300" />
              <h3 className="font-semibold">User-Scoped Data</h3>
            </div>
            <p className="text-sm leading-6 text-indigo-200/70">
              Projects, figures, and exports are filtered by ownership before they ever reach the UI.
            </p>
          </div>
        </div>
      </FloatingCard>
    </div>
  );
}
