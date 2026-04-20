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

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { generateProjectPaper } from "@/lib/backend";

const steps = [
  {
    id: 1,
    title: "Source uploaded",
    description: "Document stored and text extracted successfully.",
    icon: FileSearch,
  },
  {
    id: 2,
    title: "Writing your paper",
    description: "Drafting the manuscript sections in IEEE structure.",
    icon: Sparkles,
  },
  {
    id: 3,
    title: "Finalizing output",
    description: "Preparing references and opening the editor view.",
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

function StatusOrb({ state }: { state: ProcessingState["kind"] }) {
  const isLoading = state === "loading";
  const isSuccess = state === "success";
  const isError = state === "error";

  const Icon = isSuccess ? CheckCircle2 : isError ? AlertCircle : Loader2;

  const ringClassName = isError
    ? "border-rose-400/25 bg-rose-500/10"
    : isSuccess
      ? "border-emerald-400/25 bg-emerald-500/10"
      : "border-indigo-300/20 bg-indigo-500/12";

  const glowClassName = isError
    ? "bg-rose-500/18"
    : isSuccess
      ? "bg-emerald-500/18"
      : "bg-indigo-500/20";

  const coreClassName = isError
    ? "border-rose-400/30 bg-[linear-gradient(180deg,rgba(95,26,44,0.92)_0%,rgba(40,12,22,0.98)_100%)] text-rose-100"
    : isSuccess
      ? "border-emerald-400/30 bg-[linear-gradient(180deg,rgba(17,69,53,0.92)_0%,rgba(10,28,24,0.98)_100%)] text-emerald-50"
      : "border-indigo-300/25 bg-[linear-gradient(180deg,rgba(69,63,201,0.92)_0%,rgba(30,27,87,0.98)_100%)] text-white";

  return (
    <div className="relative mx-auto flex h-36 w-36 items-center justify-center sm:h-40 sm:w-40">
      <motion.div
        className={`absolute inset-0 rounded-full border ${ringClassName}`}
        animate={
          isLoading
            ? { scale: [1, 1.08, 1], opacity: [0.65, 1, 0.65] }
            : { scale: 1, opacity: 0.9 }
        }
        transition={{ duration: 2.4, repeat: isLoading ? Infinity : 0 }}
      />
      <motion.div
        className={`absolute inset-4 rounded-full ${glowClassName} blur-2xl`}
        animate={
          isLoading
            ? { scale: [0.95, 1.08, 0.95], opacity: [0.45, 0.85, 0.45] }
            : { scale: 1, opacity: 0.7 }
        }
        transition={{ duration: 2.2, repeat: isLoading ? Infinity : 0 }}
      />
      <motion.div
        className={`relative flex h-20 w-20 items-center justify-center rounded-full border shadow-[0_24px_80px_-40px_rgba(79,70,229,0.9)] sm:h-24 sm:w-24 ${coreClassName}`}
        animate={isLoading ? { y: [0, -4, 0] } : { y: 0 }}
        transition={{ duration: 2.2, repeat: isLoading ? Infinity : 0 }}
      >
        <Icon className={`h-8 w-8 sm:h-9 sm:w-9 ${isLoading ? "animate-spin" : ""}`} />
      </motion.div>
    </div>
  );
}

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
      if (!projectId) {
        return;
      }

      const resolvedProjectId = projectId;

      try {
        setCurrentStep(2);
        setProgress(52);

        await generateProjectPaper(resolvedProjectId, controller.signal);

        if (controller.signal.aborted) {
          return;
        }

        setCurrentStep(3);
        setProgress(92);
        setProcessingState({ kind: "success" });

        window.setTimeout(() => {
          const nextParams = new URLSearchParams({
            projectId: resolvedProjectId,
          });
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

  const totalSteps = steps.length;
  const visibleStep = Math.min(Math.max(currentStep, 1), totalSteps);
  const displayProgress = processingState.kind === "success" ? 100 : progress;
  const activeStep = steps.find((step) => step.id === visibleStep) ?? steps[0];

  const heading =
    processingState.kind === "error"
      ? "Generation paused"
      : processingState.kind === "success"
        ? "Opening the editor"
        : "Generating your research paper";

  const description =
    processingState.kind === "error"
      ? processingState.message
      : processingState.kind === "success"
        ? "Your manuscript is ready. Opening the editor now."
        : "We’re processing your source and preparing a draft for the editor.";

  const stageLabel =
    processingState.kind === "success"
      ? `Step ${totalSteps} of ${totalSteps}`
      : `Step ${visibleStep} of ${totalSteps}`;

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-4xl flex-col items-center justify-center px-4 py-8 sm:px-6">
      <motion.section
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-2xl text-center"
      >
        <StatusOrb state={processingState.kind} />

        <div className="mt-8 space-y-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.32em] text-indigo-200/72">
            {stageLabel}
          </p>
          <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">
            {heading}
          </h1>
          <p className="mx-auto max-w-xl text-sm leading-7 text-slate-300/72 sm:text-base">
            {description}
          </p>
          {title ? (
            <p className="text-sm text-slate-400/78">Project: {title}</p>
          ) : null}
        </div>

        <div className="mt-8 rounded-[28px] border border-white/8 bg-white/[0.04] p-5 shadow-[0_24px_80px_-54px_rgba(15,23,42,0.95)] backdrop-blur-xl sm:p-6">
          <div className="mb-3 flex items-center justify-between gap-4 text-sm">
            <div className="text-left">
              <p className="font-medium text-white">Workflow progress</p>
              <p className="text-xs text-slate-400">{activeStep.title}</p>
            </div>
            <span className="font-semibold text-indigo-200">
              {Math.round(displayProgress)}%
            </span>
          </div>
          <Progress
            value={displayProgress}
            className="w-full gap-0 [&_[data-slot=progress-track]]:h-2 [&_[data-slot=progress-track]]:rounded-full [&_[data-slot=progress-track]]:bg-white/10 [&_[data-slot=progress-indicator]]:rounded-full [&_[data-slot=progress-indicator]]:bg-gradient-to-r [&_[data-slot=progress-indicator]]:from-sky-400 [&_[data-slot=progress-indicator]]:via-indigo-500 [&_[data-slot=progress-indicator]]:to-violet-500"
          />
        </div>
      </motion.section>

      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.08 }}
        className="mt-8 w-full max-w-2xl"
      >
        <Card className="overflow-hidden rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(16,18,29,0.98)_0%,rgba(7,9,15,0.98)_100%)] px-5 py-5 shadow-[0_30px_110px_-70px_rgba(15,23,42,0.98)] sm:px-6 sm:py-6">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <p className="text-base font-semibold text-white">
                Processing status
              </p>
              <p className="mt-1 text-sm text-slate-300/64">
                We’ll open the editor automatically once the paper is ready.
              </p>
            </div>
            {processingState.kind === "loading" ? (
              <Badge className="border border-indigo-400/20 bg-indigo-500/12 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-indigo-200 hover:bg-indigo-500/12">
                Live
              </Badge>
            ) : null}
          </div>

          <div className="space-y-3">
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
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.08 }}
                  className={`flex items-start gap-4 rounded-2xl border px-4 py-4 transition-colors ${
                    isCompleted
                      ? "border-emerald-400/16 bg-emerald-500/8"
                      : isActive
                        ? "border-indigo-400/18 bg-indigo-500/10"
                        : isError
                          ? "border-rose-400/18 bg-rose-500/10"
                          : "border-white/8 bg-white/[0.03]"
                  }`}
                >
                  <div
                    className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border ${
                      isCompleted
                        ? "border-emerald-400/24 bg-emerald-500/14 text-emerald-200"
                        : isActive
                          ? "border-indigo-400/24 bg-indigo-500/14 text-indigo-100"
                          : isError
                            ? "border-rose-400/24 bg-rose-500/14 text-rose-200"
                            : "border-white/10 bg-white/[0.05] text-slate-400"
                    }`}
                  >
                    {isCompleted ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : isError ? (
                      <AlertCircle className="h-5 w-5" />
                    ) : isActive ? (
                      <Loader2 className="h-5 w-5 animate-spin" />
                    ) : (
                      <step.icon className="h-5 w-5" />
                    )}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2
                        className={`text-base font-semibold ${
                          isCompleted || isActive || isError
                            ? "text-white"
                            : "text-slate-300/65"
                        }`}
                      >
                        {step.title}
                      </h2>
                      {isActive ? (
                        <Badge className="border border-indigo-400/20 bg-indigo-500/12 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-indigo-200 hover:bg-indigo-500/12">
                          In progress
                        </Badge>
                      ) : null}
                    </div>
                    <p
                      className={`mt-1 text-sm leading-6 ${
                        isCompleted || isActive || isError
                          ? "text-slate-300/74"
                          : "text-slate-400/60"
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
                className="mt-4 rounded-2xl border border-rose-400/18 bg-rose-500/10 p-4"
              >
                <p className="text-sm leading-6 text-rose-100">
                  {processingState.message}
                </p>
                <div className="mt-4 flex gap-3">
                  <Button
                    onClick={() => router.push("/new")}
                    className="h-10 rounded-2xl border border-white/10 bg-white/10 px-4 text-white hover:bg-white/20"
                  >
                    Start Over
                  </Button>
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </Card>
      </motion.div>
    </div>
  );
}
