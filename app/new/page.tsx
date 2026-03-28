"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { FileUpload } from "@/components/shared/FileUpload";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FileText, ArrowRight, Loader2 } from "lucide-react";

const projectSchema = z.object({
  title: z.string().min(3, "Project title must be at least 3 characters."),
  description: z.string().optional(),
  file: z.any().refine((file) => file !== null, "Please upload a reference document (PDF/DOCX)."),
});

type ProjectFormValues = z.infer<typeof projectSchema>;

export default function NewProjectPage() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);

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
    setIsSubmitting(true);
    // Simulate API call for project creation
    setTimeout(() => {
      // Navigate to the processing screen for the next step of the demo
      router.push("/processing");
    }, 1500);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500 pb-10">
      <div>
        <h1 className="text-3xl font-bold tracking-tight mb-2">Create New Project</h1>
        <p className="text-zinc-500">
          Upload your core research material or literature to begin the automated structuring and formatting process.
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)}>
        <Card className="shadow-sm border-zinc-200">
          <CardHeader>
            <CardTitle className="text-xl">Project Details</CardTitle>
            <CardDescription>Enter the basic metadata for your new manuscript.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="title" className="text-zinc-700 font-semibold">Manuscript Title <span className="text-red-500">*</span></Label>
              <Input
                id="title"
                placeholder="e.g. Impact of AI on Modern Pedagogy"
                {...register("title")}
                className={`bg-zinc-50 border-zinc-200 focus-visible:ring-indigo-500 ${errors.title ? "border-red-500 focus-visible:ring-red-500" : ""}`}
              />
              {errors.title && <p className="text-sm text-red-500 mt-1">{errors.title.message}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="description" className="text-zinc-700 font-semibold">Abstract / Description (Optional)</Label>
              <Textarea
                id="description"
                placeholder="Briefly describe the core thesis or findings of your research..."
                {...register("description")}
                className="bg-zinc-50 border-zinc-200 focus-visible:ring-indigo-500 min-h-[100px] resize-none"
              />
            </div>

            <div className="space-y-2 pt-4 border-t border-zinc-100">
              <Label className="text-zinc-700 font-semibold">Source Document <span className="text-red-500">*</span></Label>
              <p className="text-xs text-zinc-500 mb-4">
                Upload your raw notes, initial drafts, or datasets. We'll automatically identify the core thesis and structure it.
              </p>
              
              <Controller
                name="file"
                control={control}
                render={({ field }) => (
                  <FileUpload
                    onFileSelect={(file) => field.onChange(file)}
                  />
                )}
              />
              {errors.file && <p className="text-sm text-red-500 mt-1">{errors.file.message as string}</p>}
            </div>

          </CardContent>
        </Card>

        <div className="mt-8 flex items-center justify-end gap-4">
          <Button type="button" variant="ghost" onClick={() => router.back()} className="text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100">
            Cancel
          </Button>
          <Button 
            type="submit" 
            disabled={!isValid || isSubmitting}
            className="bg-[#4F46E5] hover:bg-[#4338CA] text-white shadow-sm px-8"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Starting AI Engine...
              </>
            ) : (
              <>
                Start Processing <ArrowRight className="w-4 h-4 ml-2" />
              </>
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}
