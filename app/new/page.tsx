"use client";

import { startTransition, useState } from "react";
import { useRouter } from "next/navigation";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { ArrowRight, FileText, Loader2 } from "lucide-react";

import { FileUpload } from "@/components/shared/FileUpload";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { uploadSourceDocument } from "@/lib/backend";

const projectSchema = z.object({
  title: z.string().min(3, "Project title must be at least 3 characters."),
  description: z.string().optional(),
  file: z
    .instanceof(File, { message: "Please upload a reference document (PDF/DOCX)." })
    .nullable()
    .refine((file) => file !== null, "Please upload a reference document (PDF/DOCX)."),
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
      file: null,
    },
    mode: "onChange",
  });

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
    <div className="mx-auto max-w-3xl animate-in fade-in slide-in-from-bottom-4 space-y-8 pb-10 duration-500">
      <div>
        <h1 className="mb-2 text-3xl font-bold tracking-tight">
          Create New Project
        </h1>
        <p className="text-zinc-500">
          Upload your source document to run the real FastAPI plus Vertex AI
          generation pipeline.
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)}>
        <Card className="border-zinc-200 shadow-sm">
          <CardHeader>
            <CardTitle className="text-xl">Project Details</CardTitle>
            <CardDescription>
              Enter the manuscript context and upload the file you want the
              backend to process.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="title" className="font-semibold text-zinc-700">
                Manuscript Title <span className="text-red-500">*</span>
              </Label>
              <Input
                id="title"
                placeholder="e.g. Impact of AI on Modern Pedagogy"
                {...register("title")}
                className={`border-zinc-200 bg-zinc-50 focus-visible:ring-indigo-500 ${
                  errors.title ? "border-red-500 focus-visible:ring-red-500" : ""
                }`}
              />
              {errors.title ? (
                <p className="mt-1 text-sm text-red-500">
                  {errors.title.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label
                htmlFor="description"
                className="font-semibold text-zinc-700"
              >
                Abstract / Description (Optional)
              </Label>
              <Textarea
                id="description"
                placeholder="Briefly describe the core thesis or findings of your research..."
                {...register("description")}
                className="min-h-[100px] resize-none border-zinc-200 bg-zinc-50 focus-visible:ring-indigo-500"
              />
            </div>

            <div className="space-y-2 border-t border-zinc-100 pt-4">
              <Label className="font-semibold text-zinc-700">
                Source Document <span className="text-red-500">*</span>
              </Label>
              <p className="mb-4 text-xs text-zinc-500">
                PDF and DOCX files up to 10MB are uploaded to the FastAPI
                backend before Gemini on Vertex AI generates the paper.
              </p>

              <Controller
                name="file"
                control={control}
                render={({ field }) => (
                  <FileUpload onFileSelect={(file) => field.onChange(file)} />
                )}
              />
              {errors.file ? (
                <p className="mt-1 text-sm text-red-500">
                  {errors.file.message as string}
                </p>
              ) : null}
            </div>

            {submissionError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {submissionError}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <div className="mt-8 flex items-center justify-end gap-4">
          <Button
            type="button"
            variant="ghost"
            onClick={() => router.back()}
            className="text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={!isValid || isSubmitting}
            className="bg-[#4F46E5] px-8 text-white shadow-sm hover:bg-[#4338CA]"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Uploading Source...
              </>
            ) : (
              <>
                Start Processing <ArrowRight className="ml-2 h-4 w-4" />
              </>
            )}
          </Button>
        </div>
      </form>

      <div className="rounded-2xl border border-indigo-100 bg-indigo-50/60 p-5">
        <div className="flex items-start gap-3">
          <FileText className="mt-0.5 h-5 w-5 text-indigo-500" />
          <div className="space-y-1 text-sm text-indigo-950/80">
            <p className="font-semibold text-indigo-950">
              Live backend processing
            </p>
            <p>
              This flow uses the real `/upload` and `/generate` API endpoints,
              not demo manuscript data.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
