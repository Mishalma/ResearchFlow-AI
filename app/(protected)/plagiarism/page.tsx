"use client";

import { startTransition, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Loader2,
  ScanSearch,
  ShieldAlert,
  Wand2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { fetchGenerationJobResult, type JobResultResponse } from "@/lib/backend";

type ReportState =
  | { kind: "loading" }
  | { kind: "ready"; result: JobResultResponse }
  | { kind: "error"; message: string };

function scoreTone(value: number, acceptCutoff: number, severeCutoff: number) {
  if (value > severeCutoff) {
    return "red";
  }
  if (value > acceptCutoff) {
    return "amber";
  }
  return "emerald";
}

function formatAiPercent(value: number | null | undefined) {
  return value == null ? "--" : `${Math.round(value * 100)}%`;
}

function formatOverlapPercent(value: number | null | undefined) {
  return value == null ? "--" : `${Math.round(value * 10) / 10}%`;
}

export default function PlagiarismReportPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const projectId = searchParams.get("projectId");
  const jobId = searchParams.get("jobId");
  const [state, setState] = useState<ReportState>(() =>
    jobId ? { kind: "loading" } : { kind: "error", message: "Missing job ID for the validation report." },
  );

  useEffect(() => {
    const controller = new AbortController();
    if (!jobId) {
      return () => controller.abort();
    }
    const reportJobId = jobId;

    async function loadReport() {
      try {
        const result = await fetchGenerationJobResult(reportJobId, controller.signal);
        if (controller.signal.aborted) {
          return;
        }
        setState({ kind: "ready", result });
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          kind: "error",
          message:
            error instanceof Error
              ? error.message
              : "Unable to load the validation report right now.",
        });
      }
    }

    void loadReport();
    return () => controller.abort();
  }, [jobId]);

  const report = state.kind === "ready" ? state.result.report : null;
  const flaggedSections = useMemo(
    () =>
      report?.sections.filter(
        (section) => section.risk !== "low" || section.spans.length > 0,
      ) ?? [],
    [report],
  );

  if (state.kind === "loading") {
    return (
      <div className="mx-auto flex min-h-[calc(100vh-8rem)] max-w-3xl items-center justify-center px-4 py-12">
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="rounded-full border border-white/10 bg-white/[0.04] p-4 text-slate-100">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-white">Loading validation report</h1>
            <p className="mt-2 text-slate-400">
              Pulling the latest AI and overlap scores for this draft.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="mx-auto max-w-3xl space-y-6 px-4 py-10">
        <Card className="border-rose-400/20 bg-rose-500/10">
          <CardContent className="p-6">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-rose-200" />
              <div className="space-y-3">
                <div>
                  <h1 className="text-xl font-semibold text-white">Validation report unavailable</h1>
                  <p className="mt-1 text-sm text-rose-100/90">{state.message}</p>
                </div>
                <Button
                  onClick={() => router.push(projectId ? `/editor?projectId=${projectId}` : "/new")}
                  className="bg-white/10 text-white hover:bg-white/20"
                >
                  Back to workspace
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { result } = state;
  const aiScorePercent = report?.ai_score != null ? Math.round(report.ai_score * 100) : null;
  const overlapPercent = report ? Math.round(report.plagiarism_score * 10) / 10 : null;
  const initialAiPercent = report?.initial_ai_score != null ? Math.round(report.initial_ai_score * 100) : null;
  const initialOverlapPercent =
    report?.initial_plagiarism_score != null ? Math.round(report.initial_plagiarism_score * 10) / 10 : null;
  const finalAiPercent = report?.final_ai_score != null ? Math.round(report.final_ai_score * 100) : null;
  const finalOverlapPercent =
    report?.final_plagiarism_score != null ? Math.round(report.final_plagiarism_score * 10) / 10 : null;
  const aiTone = scoreTone(report?.ai_score ?? 0, 0.1, 0.1);
  const overlapTone = scoreTone(report?.plagiarism_score ?? 0, 10, 10);
  const accepted =
    result.final_disposition === "accepted" ||
    result.final_disposition === "accepted_after_fix";
  const fixSummary = result.fix_summary;
  const fixDiagnostic =
    fixSummary?.status === "no_change"
      ? "Model candidates were attempted, but no Desklib-improving safe rewrite was accepted."
      : fixSummary?.status === "applied"
        ? "The model accepted at least one safe section rewrite and validation rechecked the changed draft."
        : fixSummary?.fallback_reason
          ? `Fix stopped because ${fixSummary.fallback_reason.replaceAll("_", " ")}.`
          : "The fix loop did not apply a rewrite.";

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-10 pb-12">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-white">
            Validation Report
          </h1>
          <p className="mt-2 max-w-2xl text-slate-400">
            Desklib checked the AI score first, the humanizer handled flagged AI sections, and overlap review ran after the draft cleared the AI gate.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="outline"
            className="border-white/10 bg-white/[0.03] text-slate-200 hover:bg-white/[0.08]"
            onClick={() => {
              startTransition(() => {
                router.refresh();
              });
            }}
          >
            Refresh
          </Button>
          <Button
            className="bg-white text-zinc-900 hover:bg-zinc-200"
            onClick={() => {
              startTransition(() => {
                router.push(projectId ? `/editor?projectId=${projectId}` : "/editor");
              });
            }}
          >
            {accepted ? "Open Editor" : "Open Latest Draft"}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className={`border ${aiTone === "red" ? "border-rose-400/20" : aiTone === "amber" ? "border-amber-400/20" : "border-emerald-400/20"} bg-[#181816]`}>
          <CardContent className="p-6">
            <p className="text-sm text-slate-400">AI Risk Score</p>
            <div className="mt-3 flex items-center gap-3">
              <div className={`rounded-full p-3 ${aiTone === "red" ? "bg-rose-500/10 text-rose-200" : aiTone === "amber" ? "bg-amber-500/10 text-amber-200" : "bg-emerald-500/10 text-emerald-200"}`}>
                <ScanSearch className="h-5 w-5" />
              </div>
              <div>
                <p className="text-3xl font-semibold text-white">
                  {aiScorePercent == null ? "--" : `${aiScorePercent}%`}
                </p>
                <p className="text-sm text-slate-400">
                  {report?.routing_decision === "accepted"
                    ? "Within the 10% acceptance gate"
                    : "Above the 10% AI threshold or still pending review"}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className={`border ${overlapTone === "red" ? "border-rose-400/20" : overlapTone === "amber" ? "border-amber-400/20" : "border-emerald-400/20"} bg-[#181816]`}>
          <CardContent className="p-6">
            <p className="text-sm text-slate-400">Overlap Score</p>
            <div className="mt-3 flex items-center gap-3">
              <div className={`rounded-full p-3 ${overlapTone === "red" ? "bg-rose-500/10 text-rose-200" : overlapTone === "amber" ? "bg-amber-500/10 text-amber-200" : "bg-emerald-500/10 text-emerald-200"}`}>
                <ShieldAlert className="h-5 w-5" />
              </div>
              <div>
                <p className="text-3xl font-semibold text-white">
                  {overlapPercent == null ? "--" : `${overlapPercent}%`}
                </p>
                <p className="text-sm text-slate-400">
                  Final overlap score against the uploaded source.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border border-white/10 bg-[#181816]">
          <CardContent className="p-6">
            <p className="text-sm text-slate-400">Decision</p>
            <div className="mt-3 flex items-center gap-3">
              <div className={`rounded-full p-3 ${accepted ? "bg-emerald-500/10 text-emerald-200" : "bg-amber-500/10 text-amber-200"}`}>
                {accepted ? (
                  <CheckCircle2 className="h-5 w-5" />
                ) : (
                  <AlertTriangle className="h-5 w-5" />
                )}
              </div>
              <div>
                <p className="text-lg font-semibold capitalize text-white">
                  {result.final_disposition.replaceAll("_", " ")}
                </p>
                <p className="text-sm text-slate-400">
                  {report?.decision_summary ?? "Validation summary unavailable."}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border border-white/10 bg-[#181816]">
        <CardContent className="p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-xl font-semibold text-white">Workflow Summary</h2>
              <p className="mt-1 text-sm text-slate-400">
                The workflow runs Desklib AI detection first, applies targeted humanizer fixes when needed, and checks source overlap after the AI score reaches the acceptance gate.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge
                variant="outline"
                className="border-white/10 bg-white/[0.03] text-slate-200"
              >
                Final status {result.final_disposition.replaceAll("_", " ")}
              </Badge>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-wide text-slate-500">Acceptance Gate</p>
              <p className="mt-2 text-lg font-semibold text-white">AI &lt;= 10% before overlap &lt;= 10%</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-wide text-slate-500">Fix Loop</p>
              <p className="mt-2 text-lg font-semibold text-white">
                {fixSummary?.attempted ? `${fixSummary.iterations} pass${fixSummary.iterations === 1 ? "" : "es"}` : "Not needed"}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-wide text-slate-500">Latest Draft</p>
              <p className="mt-2 break-all text-sm font-semibold text-white">
                {result.artifacts.draft_v5_uri ??
                  result.artifacts.draft_v4_uri ??
                  result.artifacts.draft_v3_uri ??
                  result.artifacts.draft_v2_uri ??
                  result.artifacts.draft_v1_uri ??
                  "Unavailable"}
              </p>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-wide text-slate-500">Initial Scores</p>
              <p className="mt-2 text-sm text-slate-300">
                AI {initialAiPercent == null ? "--" : `${initialAiPercent}%`} and overlap{" "}
                {initialOverlapPercent == null ? "--" : `${initialOverlapPercent}%`}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-wide text-slate-500">Final Scores</p>
              <p className="mt-2 text-sm text-slate-300">
                AI {finalAiPercent == null ? "--" : `${finalAiPercent}%`} and overlap{" "}
                {finalOverlapPercent == null ? "--" : `${finalOverlapPercent}%`}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {fixSummary?.attempted ? (
        <Card className="border border-white/10 bg-[#181816]">
          <CardContent className="p-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <div className="rounded-full bg-white/[0.04] p-3 text-slate-100">
                    <Wand2 className="h-5 w-5" />
                  </div>
                  <div>
                    <h2 className="text-xl font-semibold text-white">AI Fix Loop</h2>
                    <p className="mt-1 text-sm text-slate-400">
                      {fixDiagnostic}
                    </p>
                  </div>
                </div>
              </div>
              <Badge
                variant="outline"
                className={
                  fixSummary.status === "applied"
                    ? "border-emerald-300/20 bg-emerald-500/10 text-emerald-100"
                    : "border-rose-300/20 bg-rose-500/10 text-rose-100"
                }
              >
                {fixSummary.status.replaceAll("_", " ")}
              </Badge>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">Iterations</p>
                <p className="mt-2 text-2xl font-semibold text-white">{fixSummary.iterations}</p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">Rewrite Mode</p>
                <p className="mt-2 text-lg font-semibold capitalize text-white">
                  {fixSummary.rewriter_mode ?? "Unavailable"}
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">Changed Sections</p>
                <p className="mt-2 text-lg font-semibold text-white">
                  {fixSummary.changed_sections.length}
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">Strategy</p>
                <p className="mt-2 text-lg font-semibold capitalize text-white">
                  {fixSummary.strategy?.replaceAll("_", " ") ?? "Unavailable"}
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">Candidates</p>
                <p className="mt-2 text-lg font-semibold text-white">
                  {fixSummary.accepted_candidate_count ?? 0}/{fixSummary.candidate_count ?? 0} accepted
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">Best Attempted Scores</p>
                <p className="mt-2 text-lg font-semibold text-white">
                  AI {formatAiPercent(fixSummary.best_candidate_ai_score)} and overlap{" "}
                  {formatOverlapPercent(fixSummary.best_candidate_overlap_score)}
                </p>
              </div>
            </div>

            {fixSummary.changed_sections.length > 0 ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {fixSummary.changed_sections.map((sectionId) => (
                  <Badge
                    key={sectionId}
                    variant="outline"
                    className="border-white/10 bg-white/[0.03] text-slate-200"
                  >
                    {sectionId.replaceAll("_", " ")}
                  </Badge>
                ))}
              </div>
            ) : null}

            {fixSummary.failure_reasons?.length ? (
              <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">Failure Signals</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {fixSummary.failure_reasons.slice(0, 6).map((reason) => (
                    <Badge
                      key={reason}
                      variant="outline"
                      className="border-white/10 bg-white/[0.03] text-slate-200"
                    >
                      {reason.replaceAll("_", " ")}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Card className="border border-white/10 bg-[#181816]">
        <CardContent className="p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold text-white">Flagged Sections</h2>
              <p className="mt-1 text-sm text-slate-400">
                Section-level summaries from the final validation pass.
              </p>
            </div>
            <Badge
              variant="outline"
              className="border-white/10 bg-white/[0.03] text-slate-200"
            >
              {flaggedSections.length} flagged
            </Badge>
          </div>

          <div className="mt-6 space-y-4">
            {flaggedSections.length === 0 ? (
              <div className="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 p-4 text-sm text-emerald-100">
                No section-level issues remained above the final acceptance threshold.
              </div>
            ) : (
              flaggedSections.map((section) => (
                <div
                  key={section.section_name}
                  className="rounded-2xl border border-white/10 bg-white/[0.02] p-4"
                >
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-lg font-semibold capitalize text-white">
                          {section.section_name.replaceAll("_", " ")}
                        </h3>
                        <Badge
                          variant="outline"
                          className={
                            section.risk === "severe"
                              ? "border-rose-300/20 bg-rose-500/10 text-rose-100"
                              : "border-amber-300/20 bg-amber-500/10 text-amber-100"
                          }
                        >
                          {section.risk}
                        </Badge>
                      </div>
                      <p className="mt-2 text-sm text-slate-300">
                        {section.summary[0] ?? "This section stayed above the product threshold."}
                      </p>
                    </div>

                    <div className="grid grid-cols-2 gap-3 text-sm text-slate-300 md:min-w-[14rem]">
                      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                        <p className="text-xs uppercase tracking-wide text-slate-500">AI</p>
                        <p className="mt-1 text-lg font-semibold text-white">
                          {section.ai_score == null ? "--" : `${Math.round(section.ai_score * 100)}%`}
                        </p>
                      </div>
                      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                        <p className="text-xs uppercase tracking-wide text-slate-500">Overlap</p>
                        <p className="mt-1 text-lg font-semibold text-white">
                          {Math.round(section.plagiarism_score * 10) / 10}%
                        </p>
                      </div>
                    </div>
                  </div>

                  {section.spans.length > 0 ? (
                    <div className="mt-4 space-y-3">
                      {section.spans.slice(0, 3).map((span, index) => (
                        <div
                          key={`${section.section_name}-${index}-${span.start_char}`}
                          className="rounded-xl border border-white/8 bg-[#111110] p-3"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge
                              variant="outline"
                              className="border-white/10 bg-white/[0.03] text-slate-200"
                            >
                              {span.classification.replaceAll("_", " ")}
                            </Badge>
                            <span className="text-xs text-slate-500">
                              Similarity {span.similarity_score == null ? "--" : `${Math.round(span.similarity_score * 100)}%`}
                            </span>
                          </div>
                          <p className="mt-2 line-clamp-3 text-sm leading-6 text-slate-300">
                            {span.matched_text}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
