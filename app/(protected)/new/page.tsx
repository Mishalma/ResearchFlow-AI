"use client";

import { startTransition, useState } from "react";
import { useRouter } from "next/navigation";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { ArrowRight, Loader2, Sparkles } from "lucide-react";

import { FileUpload } from "@/components/shared/FileUpload";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { uploadSourceDocument } from "@/lib/backend";

const projectSchema = z.object({
  title: z.string().min(3, "Project title must be at least 3 characters."),
  description: z.string().optional(),
  file: z
    .instanceof(File, {
      message: "Please upload a reference document (PDF/DOCX).",
    })
    .optional(),
});

type ProjectFormValues = z.infer<typeof projectSchema>;

export default function NewProjectPage() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isValid },
  } = useForm<ProjectFormValues>({
    resolver: zodResolver(projectSchema),
    defaultValues: {
      title: "",
      description: "",
      file: undefined,
    },
    mode: "onChange",
  });

  const selectedFile = useWatch({ control, name: "file" });
  const canSubmit = isValid && Boolean(selectedFile) && !isSubmitting;

  const onSubmit = async (data: ProjectFormValues) => {
    if (!data.file) {
      return;
    }

    setIsSubmitting(true);
    setSubmissionError(null);

    try {
      const uploadResponse = await uploadSourceDocument(data.file);
      const params = new URLSearchParams({
        projectId: uploadResponse.project_id,
        title: data.title,
      });

      startTransition(() => {
        router.push(`/processing?${params.toString()}`);
      });
    } catch (error) {
      setSubmissionError(
        error instanceof Error
          ? error.message
          : "Unable to upload your source document right now.",
      );
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl animate-in fade-in slide-in-from-bottom-4 space-y-8 pb-12 duration-500">
      <div className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          Create a new manuscript workspace
        </h1>
        <p className="max-w-2xl text-sm leading-7 text-slate-300/72 sm:text-base">
          Add a title, include a short research summary if you want, and upload
          your source document to begin processing.
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)}>
        <Card className="relative overflow-hidden rounded-[32px] border border-white/10 bg-[linear-gradient(180deg,rgba(16,18,29,0.98)_0%,rgba(7,9,15,0.98)_100%)] py-0 shadow-[0_32px_120px_-70px_rgba(15,23,42,0.95)]">
          <div
            aria-hidden
            className="pointer-events-none absolute -left-16 top-0 h-48 w-48 rounded-full bg-sky-400/10 blur-3xl"
          />
          <div
            aria-hidden
            className="pointer-events-none absolute -right-16 bottom-0 h-56 w-56 rounded-full bg-indigo-500/10 blur-3xl"
          />

          <CardHeader className="relative gap-3 border-b border-white/8 px-6 pt-6 pb-5 sm:px-8 sm:pt-8">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="space-y-2">
                <CardTitle className="text-2xl font-semibold text-white">
                  Project details
                </CardTitle>
                <CardDescription className="max-w-2xl text-sm leading-6 text-slate-300/66">
                  Add the manuscript context and source file you want PaperEasy
                  to process next.
                </CardDescription>
              </div>

              <div className="inline-flex items-center gap-2 self-start rounded-full border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs font-medium text-slate-300">
                <Sparkles className="h-3.5 w-3.5 text-indigo-300" />
                Standard setup
              </div>
            </div>
          </CardHeader>

          <CardContent className="relative space-y-8 px-6 py-6 sm:px-8 sm:py-8">
            <section className="space-y-6 rounded-[28px] border border-white/8 bg-white/[0.03] p-5 sm:p-6">
              <div className="space-y-1">
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">
                  Manuscript context
                </p>
                <p className="text-sm text-slate-300/64">
                  Capture the paper title and optional summary before you upload
                  the document.
                </p>
              </div>

              <div className="space-y-2.5">
                <Label
                  htmlFor="title"
                  className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-300/78"
                >
                  Manuscript title <span className="text-rose-300">*</span>
                </Label>
                <Input
                  id="title"
                  placeholder="e.g. Impact of AI on Modern Pedagogy"
                  {...register("title")}
                  className={`h-12 rounded-2xl border-white/10 bg-black/20 px-4 text-white placeholder:text-slate-500 shadow-inner shadow-black/20 focus-visible:border-indigo-300/35 focus-visible:ring-4 focus-visible:ring-indigo-400/12 ${
                    errors.title
                      ? "border-rose-400/45 focus-visible:border-rose-400/45 focus-visible:ring-rose-400/12"
                      : ""
                  }`}
                />
                {errors.title ? (
                  <p className="mt-1 text-sm text-rose-200">
                    {errors.title.message}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2.5">
                <Label
                  htmlFor="description"
                  className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-300/78"
                >
                  Abstract or description
                </Label>
                <Textarea
                  id="description"
                  placeholder="Briefly describe the core thesis, scope, or findings of your research..."
                  {...register("description")}
                  className="min-h-[132px] resize-none rounded-2xl border-white/10 bg-black/20 px-4 py-3 text-white placeholder:text-slate-500 shadow-inner shadow-black/20 focus-visible:border-indigo-300/35 focus-visible:ring-4 focus-visible:ring-indigo-400/12"
                />
              </div>
            </section>

            <section className="space-y-4 rounded-[28px] border border-white/8 bg-white/[0.03] p-5 sm:p-6">
              <div className="space-y-1">
                <Label className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-300/78">
                  Source document <span className="text-rose-300">*</span>
                </Label>
                <p className="text-sm text-slate-300/64">
                  Upload the primary document you want to use for this project.
                </p>
              </div>

              <Controller
                name="file"
                control={control}
                render={({ field }) => (
                  <FileUpload
                    onFileSelect={(file) => field.onChange(file ?? undefined)}
                  />
                )}
              />

              {errors.file ? (
                <p className="mt-1 text-sm text-rose-200">
                  {errors.file.message as string}
                </p>
              ) : null}
            </section>

            {submissionError ? (
              <div className="rounded-2xl border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                {submissionError}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-end">
          <Button
            type="button"
            variant="ghost"
            onClick={() => router.back()}
            className="h-11 rounded-2xl border border-white/8 bg-white/[0.04] px-5 text-slate-300 hover:bg-white/[0.08] hover:text-white"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={!canSubmit}
            className="h-11 rounded-2xl border border-indigo-300/15 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 px-6 text-white shadow-[0_0_28px_rgba(59,130,246,0.22)] hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Uploading source...
              </>
            ) : (
              <>
                Start Processing <ArrowRight className="ml-2 h-4 w-4" />
              </>
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}
