"use client";

import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  CheckCircle2,
  FileSearch,
  FileText,
  Layers,
  Loader2,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  createGenerationJob,
  fetchGenerationJob,
  fetchGenerationJobResult,
} from "@/lib/backend";

const steps = [
  {
    id: 1,
    title: "Source uploaded",
    description: "Document stored and text extracted successfully.",
    icon: FileSearch,
  },
  {
    id: 2,
    title: "Generating manuscript",
    description: "Structuring sections, drafting content, adding citations, and formatting the paper.",
    icon: Sparkles,
  },
  {
    id: 3,
    title: "Running validation",
    description: "Scoring AI patterns and source overlap before final approval.",
    icon: Layers,
  },
  {
    id: 4,
    title: "Finalizing result",
    description: "Preparing the accepted draft or review report.",
    icon: FileText,
  },
];

type ProcessingState =
  | { kind: "loading" }
  | { kind: "success" }
  | { kind: "error"; message: string };

type ProcessingClientPageProps = {
  projectId: string | null;
  jobId: string | null;
  title: string | null;
};

function buildJobIdempotencyKey(projectId: string) {
  return `workflow-project:${projectId}:generate`;
}

function buildProcessingUrl(projectId: string, title: string | null, jobId: string) {
  const params = new URLSearchParams({ projectId, jobId });
  if (title) {
    params.set("title", title);
  }

  return `/processing?${params.toString()}`;
}

function ProgressRing({
  value,
  state,
}: {
  value: number;
  state: ProcessingState["kind"];
}) {
  const isLoading = state === "loading";
  const isSuccess = state === "success";
  const isError = state === "error";

  const Icon = isSuccess ? CheckCircle2 : isError ? AlertCircle : Loader2;
  const progressValue = Math.max(0, Math.min(100, Math.round(value)));

  const progressColor = isError
    ? "#fb7185"
    : isSuccess
      ? "#22c55e"
      : "#f3f4f6";

  return (
    <div className="relative mx-auto h-32 w-32 sm:h-36 sm:w-36">
      <div
        className="absolute inset-0 rounded-full"
        style={{
          background: `conic-gradient(${progressColor} ${progressValue * 3.6}deg, rgba(255,255,255,0.14) 0deg)`,
        }}
      />
      <div className="absolute inset-[4px] rounded-full bg-[#171715]" />
      <div className="absolute inset-[7px] rounded-full border border-white/8 bg-[#21211f]" />

      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <div className="mb-2 flex h-7 w-7 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-slate-200">
          <Icon className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
        </div>
        <p className="text-3xl font-semibold leading-none text-white">
          {progressValue}%
        </p>
        <p className="mt-1 text-sm text-slate-400">complete</p>
      </div>
    </div>
  );
}

export default function ProcessingClientPage({
  projectId,
  jobId: initialJobId,
  title,
}: ProcessingClientPageProps) {
  const router = useRouter();
  const redirectScheduledRef = useRef(false);
  const [jobId, setJobId] = useState<string | null>(initialJobId);
  const [currentStep, setCurrentStep] = useState(projectId ? 1 : 1);
  const [progress, setProgress] = useState(projectId ? 25 : 0);
  const [processingState, setProcessingState] = useState<ProcessingState>(() =>
    projectId
      ? { kind: "loading" }
      : {
          kind: "error",
          message: "Missing project ID. Please start from the new project page.",
        },
  );

  useEffect(() => {
    setJobId(initialJobId);
  }, [initialJobId]);

  useEffect(() => {
    const controller = new AbortController();

    if (!projectId || jobId) {
      return () => controller.abort();
    }

    const currentProjectId = projectId;

    async function ensureJob() {
      try {
        setCurrentStep(1);
        setProgress(25);
        const createdJob = await createGenerationJob(
          currentProjectId,
          buildJobIdempotencyKey(currentProjectId),
          controller.signal,
        );

        if (controller.signal.aborted) {
          return;
        }

        setJobId(createdJob.job_id);
        startTransition(() => {
          router.replace(
            buildProcessingUrl(currentProjectId, title, createdJob.job_id),
          );
        });
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

    void ensureJob();

    return () => controller.abort();
  }, [jobId, projectId, router, title]);

  useEffect(() => {
    const controller = new AbortController();

    if (!projectId || !jobId) {
      return () => controller.abort();
    }

    const currentProjectId = projectId;
    const currentJobId = jobId;
    let pollTimer: number | null = null;
    let active = true;

    async function pollJob() {
      try {
        const job = await fetchGenerationJob(currentJobId, controller.signal);

        if (!active || controller.signal.aborted) {
          return;
        }

        setProgress(job.progress.percent);
        if (job.progress.current_step === "generation") {
          setCurrentStep(2);
        } else if (job.progress.current_step === "validation") {
          setCurrentStep(3);
        } else if (job.progress.current_step === "finalizing") {
          setCurrentStep(4);
        } else if (job.status === "DONE") {
          setCurrentStep(4);
        } else if (job.status === "FAILED") {
          setCurrentStep((previous) => Math.max(previous, 2));
        } else {
          setCurrentStep(1);
        }

        if (job.status === "DONE") {
          if (pollTimer !== null) {
            window.clearInterval(pollTimer);
            pollTimer = null;
          }
          const result = await fetchGenerationJobResult(currentJobId, controller.signal);

          if (!active || controller.signal.aborted) {
            return;
          }

          setProcessingState({ kind: "success" });
          if (!redirectScheduledRef.current) {
            redirectScheduledRef.current = true;
            window.setTimeout(() => {
              startTransition(() => {
                if (result.final_disposition === "accepted" && result.editor_url) {
                  router.push(result.editor_url);
                  return;
                }
                const nextParams = new URLSearchParams({
                  projectId: currentProjectId,
                  jobId: currentJobId,
                });
                router.push(`/plagiarism?${nextParams.toString()}`);
              });
            }, 500);
          }
          return;
        }

        if (job.status === "FAILED") {
          if (pollTimer !== null) {
            window.clearInterval(pollTimer);
            pollTimer = null;
          }
          setProcessingState({
            kind: "error",
            message:
              job.error?.message ||
              "Paper generation failed before the editor could be opened.",
          });
          return;
        }

        setProcessingState({ kind: "loading" });
      } catch (error) {
        if (!active || controller.signal.aborted) {
          return;
        }

        setProcessingState({
          kind: "error",
          message:
            error instanceof Error
              ? error.message
              : "Unable to load the workflow status right now.",
        });
      }
    }

    void pollJob();
    pollTimer = window.setInterval(() => {
      void pollJob();
    }, 2000);

    return () => {
      active = false;
      controller.abort();
      if (pollTimer !== null) {
        window.clearInterval(pollTimer);
      }
    };
  }, [jobId, projectId, router, title]);

  const totalSteps = steps.length;
  const visibleStep = Math.min(Math.max(currentStep, 1), totalSteps);
  const displayProgress = processingState.kind === "success" ? 100 : progress;

  const heading =
    processingState.kind === "error"
      ? "Generation paused"
      : processingState.kind === "success"
        ? "Opening your editor"
        : "Generating your manuscript";

  const description =
    processingState.kind === "error"
      ? processingState.message
      : processingState.kind === "success"
        ? "Your validation report is ready. The next workspace will open automatically."
        : "Structuring the paper, drafting sections, adding citations, and running fast validation.\nThe next workspace will open automatically when ready.";

  const statusLabel =
    processingState.kind === "error"
      ? "Processing - paused"
      : `Processing - step ${processingState.kind === "success" ? totalSteps : visibleStep} of ${totalSteps}`;

  const footerLabel =
    processingState.kind === "loading"
      ? "~ Auto-opening when complete"
      : processingState.kind === "success"
        ? "Ready now"
        : "Generation interrupted";

  const stepIndicator = useMemo(
    () =>
      steps.map((step) => {
        if (processingState.kind === "success") {
          return "complete";
        }
        if (processingState.kind === "error" && step.id === visibleStep) {
          return "error";
        }
        if (step.id < visibleStep) {
          return "complete";
        }
        if (step.id === visibleStep) {
          return "active";
        }
        return "idle";
      }),
    [processingState.kind, visibleStep],
  );

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-4xl items-start justify-center px-4 py-10 sm:px-6 sm:py-14">
      <motion.section
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-[34rem]"
      >
        <div className="flex justify-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-4 py-1.5 text-sm font-medium text-slate-200">
            <span className="h-2 w-2 rounded-full bg-lime-400" />
            {statusLabel}
          </div>
        </div>

        <div className="mt-9 flex justify-center">
          <ProgressRing value={displayProgress} state={processingState.kind} />
        </div>

        <div className="mt-10 text-center">
          <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-[2.2rem]">
            {heading}
          </h1>
          <p className="mx-auto mt-3 max-w-xl whitespace-pre-line text-lg leading-8 text-slate-300/78">
            {description}
          </p>
          {title ? (
            <div className="mt-5 flex justify-center">
              <div className="inline-flex max-w-full items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-sm text-slate-300">
                <FileText className="h-4 w-4 shrink-0 text-slate-400" />
                <span className="truncate">{title}</span>
              </div>
            </div>
          ) : null}
        </div>

        <div className="mt-12 pl-2 sm:pl-0">
          <div className="relative">
            <div className="absolute left-[0.95rem] top-5 bottom-5 w-px bg-white/10" />

            <div className="space-y-7">
              {steps.map((step, index) => {
                const status = stepIndicator[index];
                const isCompleted = status === "complete";
                const isActive = status === "active";
                const isError = status === "error";
                const StepIcon = isCompleted
                  ? CheckCircle2
                  : isError
                    ? AlertCircle
                    : isActive
                      ? Loader2
                      : step.icon;

                return (
                  <motion.div
                    key={step.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.08 }}
                    className="relative flex items-start gap-5"
                  >
                    <div
                      className={`relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border ${
                        isCompleted
                          ? "border-lime-500/40 bg-lime-500/18 text-lime-300"
                          : isActive
                            ? "border-white/20 bg-white/[0.05] text-slate-100"
                            : isError
                              ? "border-rose-400/30 bg-rose-500/12 text-rose-200"
                              : "border-white/12 bg-[#232321] text-slate-500"
                      }`}
                    >
                      <StepIcon
                        className={`h-4.5 w-4.5 ${isActive ? "animate-spin" : ""}`}
                      />
                    </div>

                    <div className="min-w-0 flex-1 pt-0.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2
                          className={`text-[1.35rem] font-semibold leading-none ${
                            isCompleted || isActive || isError
                              ? "text-white"
                              : "text-slate-500"
                          }`}
                        >
                          {step.title}
                        </h2>
                        {isActive ? (
                          <span className="inline-flex items-center rounded-full border border-white/12 bg-white/[0.04] px-3 py-1 text-xs font-medium text-slate-200">
                            In progress
                          </span>
                        ) : null}
                      </div>
                      <p
                        className={`mt-2 text-[1.15rem] leading-8 ${
                          isCompleted || isActive || isError
                            ? "text-slate-300/84"
                            : "text-slate-500"
                        }`}
                      >
                        {step.description}
                      </p>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </div>
        </div>

        <AnimatePresence mode="wait">
          {processingState.kind === "error" ? (
            <motion.div
              key="error"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-8 rounded-2xl border border-rose-400/18 bg-rose-500/10 p-4"
            >
              <p className="text-sm leading-6 text-rose-100">
                {processingState.message}
              </p>
              <div className="mt-4">
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

        <div className="mt-10 flex items-center justify-between border-t border-white/10 pt-4 text-sm text-slate-400">
          <span>{footerLabel}</span>
          <div className="flex items-center gap-2">
            {steps.map((step, index) => {
              const status = stepIndicator[index];

              return (
                <span
                  key={step.id}
                  className={`h-2 w-2 rounded-full ${
                    status === "complete" || status === "active"
                      ? "bg-white"
                      : status === "error"
                        ? "bg-rose-300"
                        : "bg-white/30"
                  }`}
                />
              );
            })}
          </div>
        </div>
      </motion.section>
    </div>
  );
}
