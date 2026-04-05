"use client";

import { startTransition, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  CheckCircle2,
  FileSearch,
  Layers,
  Loader2,
  Sparkles,
} from "lucide-react";

import { AICore } from "@/components/3d/AICore";
import { SceneCanvas } from "@/components/3d/SceneCanvas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { generateProjectPaper } from "@/lib/backend";

const steps = [
  {
    id: 1,
    title: "Source Uploaded",
    description:
      "Your file has been stored by the FastAPI backend and its text has been extracted successfully.",
    icon: FileSearch,
  },
  {
    id: 2,
    title: "Generating Sections",
    description:
      "Gemini on Vertex AI is structuring and improving the abstract, introduction, methodology, and conclusion.",
    icon: Sparkles,
  },
  {
    id: 3,
    title: "Finalizing Paper",
    description:
      "The backend is attaching references, formatting the output, and preparing the editor view.",
    icon: Layers,
  },
];

type ProcessingState =
  | { kind: "loading" }
  | { kind: "success" }
  | { kind: "error"; message: string };

type ProcessingClientPageProps = {
  projectId: string | null;
  title: string | null;
};

export default function ProcessingClientPage({
  projectId,
  title,
}: ProcessingClientPageProps) {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [progress, setProgress] = useState(projectId ? 18 : 0);
  const [processingState, setProcessingState] = useState<ProcessingState>(() =>
    projectId
      ? { kind: "loading" }
      : {
          kind: "error",
          message: "Missing project ID. Please start from the new project page.",
        },
  );

  useEffect(() => {
    const controller = new AbortController();

    if (!projectId) {
      return () => controller.abort();
    }

    async function processProject() {
      try {
        setCurrentStep(2);
        setProgress(52);

        await generateProjectPaper(projectId, controller.signal);

        if (controller.signal.aborted) {
          return;
        }

        setCurrentStep(3);
        setProgress(92);
        setProcessingState({ kind: "success" });

        window.setTimeout(() => {
          const nextParams = new URLSearchParams({ projectId });
          if (title) {
            nextParams.set("title", title);
          }

          startTransition(() => {
            router.push(`/editor?${nextParams.toString()}`);
          });
        }, 500);
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }

        setProcessingState({
          kind: "error",
          message:
            error instanceof Error
              ? error.message
              : "Unable to generate the paper right now.",
        });
      }
    }

    void processProject();

    return () => controller.abort();
  }, [projectId, router, title]);

  const displayProgress = processingState.kind === "success" ? 100 : progress;

  const heading =
    processingState.kind === "error"
      ? "Generation paused"
      : processingState.kind === "success"
        ? "Opening the editor"
        : "Synthesizing your Research";

  const description =
    processingState.kind === "error"
      ? processingState.message
      : processingState.kind === "success"
        ? "The backend returned a generated paper. Redirecting to the editor now."
        : "This screen reflects the live backend request while FastAPI and Vertex AI process your paper.";

  return (
    <div className="relative mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-2xl flex-col items-center justify-center px-4">
      <div className="pointer-events-none absolute top-0 left-1/2 -mt-20 h-96 w-full max-w-lg -translate-x-1/2 opacity-80">
        <SceneCanvas className="h-full w-full">
          <AICore fast={processingState.kind !== "error"} />
        </SceneCanvas>
      </div>

      <div className="relative z-10 mt-32 mb-10 text-center">
        <h1 className="mb-3 text-3xl font-bold tracking-tight text-white drop-shadow-[0_0_15px_rgba(79,70,229,0.5)] md:text-5xl">
          {heading}
        </h1>
        <p className="text-lg text-indigo-200/80">{description}</p>
      </div>

      <Card className="relative z-10 w-full overflow-hidden rounded-2xl border border-white/10 bg-black/40 p-8 shadow-[0_0_30px_rgba(79,70,229,0.15)] backdrop-blur-xl">
        <div className="pointer-events-none absolute top-0 left-1/2 h-32 w-3/4 -translate-x-1/2 rounded-[100%] bg-indigo-500 opacity-10 blur-3xl" />

        <div className="relative mb-10">
          <div className="mb-3 flex justify-between text-sm font-semibold text-indigo-200">
            <span>Workflow Progress</span>
            <span className="text-indigo-400 drop-shadow-[0_0_5px_rgba(129,140,248,0.8)]">
              {Math.round(displayProgress)}%
            </span>
          </div>
          <Progress
            value={displayProgress}
            className="h-2 bg-white/10 [&>div]:bg-indigo-500"
          />
        </div>

        <div className="relative space-y-6">
          <div className="absolute top-6 bottom-6 left-6 hidden w-0.5 bg-white/10 sm:block" />

          {steps.map((step, index) => {
            const isCompleted =
              processingState.kind === "success" || currentStep > step.id;
            const isActive =
              processingState.kind === "loading" && currentStep === step.id;
            const isError =
              processingState.kind === "error" && currentStep === step.id;

            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.15 }}
                className={`relative flex items-start gap-5 rounded-xl border p-4 transition-all duration-500 ${
                  isActive
                    ? "border-indigo-500/20 bg-indigo-500/10 shadow-[inset_0_0_20px_rgba(79,70,229,0.1)]"
                    : isError
                      ? "border-rose-500/20 bg-rose-500/10"
                      : "border-transparent"
                }`}
              >
                <div
                  className={`relative z-10 flex h-12 w-12 shrink-0 items-center justify-center rounded-full border-2 transition-all duration-500 ${
                    isCompleted
                      ? "border-emerald-500/50 bg-emerald-500/20 text-emerald-400"
                      : isError
                        ? "border-rose-500/50 bg-rose-500/20 text-rose-300"
                        : isActive
                          ? "border-indigo-400 bg-indigo-500/20 text-indigo-300"
                          : "border-white/10 bg-white/5 text-white/30"
                  }`}
                >
                  {isCompleted ? (
                    <CheckCircle2 className="h-6 w-6" />
                  ) : isError ? (
                    <AlertCircle className="h-5 w-5" />
                  ) : isActive ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <step.icon className="h-5 w-5" />
                  )}
                </div>

                <div className="min-w-0 flex-1 pt-1.5">
                  <div className="mb-1 flex items-center gap-3">
                    <h3
                      className={`text-lg font-bold transition-colors duration-500 ${
                        isActive || isCompleted ? "text-white" : "text-white/40"
                      }`}
                    >
                      {step.title}
                    </h3>
                    {isActive ? (
                      <Badge className="border border-indigo-500/30 bg-indigo-500/20 px-2 py-0 text-[10px] font-semibold uppercase tracking-wider text-indigo-300 hover:bg-indigo-500/30">
                        Live
                      </Badge>
                    ) : null}
                  </div>
                  <p
                    className={`text-sm transition-colors duration-500 ${
                      isActive || isCompleted
                        ? "text-indigo-200/70"
                        : "text-white/30"
                    }`}
                  >
                    {step.description}
                  </p>
                </div>
              </motion.div>
            );
          })}
        </div>

        <AnimatePresence mode="wait">
          {processingState.kind === "error" ? (
            <motion.div
              key="error"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-8 rounded-xl border border-rose-500/20 bg-rose-500/10 p-4"
            >
              <p className="text-sm text-rose-100">{processingState.message}</p>
              <div className="mt-4 flex gap-3">
                <Button
                  onClick={() => router.push("/new")}
                  className="bg-white/10 text-white hover:bg-white/20"
                >
                  Start Over
                </Button>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </Card>
    </div>
  );
}
