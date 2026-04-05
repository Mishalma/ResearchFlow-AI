"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Quote,
  Save,
  Sparkles,
} from "lucide-react";

import { FloatingCard } from "@/components/3d/FloatingCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  fetchProject,
  saveProjectSections,
  type PaperSections,
  type ProjectResponse,
} from "@/lib/backend";

type EditorState =
  | { kind: "loading" }
  | { kind: "success"; project: ProjectResponse; title: string }
  | { kind: "error"; message: string };

type EditableSectionKey = keyof PaperSections;

type EditorClientPageProps = {
  projectId: string | null;
  title: string | null;
};

type SectionDescriptor = {
  id: EditableSectionKey | "references";
  title: string;
  content: string;
  editable: boolean;
};

const editableSectionConfig: Array<{
  id: EditableSectionKey;
  title: string;
}> = [
  { id: "abstract", title: "Abstract" },
  { id: "introduction", title: "1. Introduction" },
  { id: "methodology", title: "2. Methodology" },
  { id: "conclusion", title: "3. Conclusion" },
];

function getProjectTitle(project: ProjectResponse, titleOverride: string | null) {
  if (titleOverride?.trim()) {
    return titleOverride.trim();
  }

  return project.file_name.replace(/\.[^/.]+$/, "");
}

function getProjectSections(project: ProjectResponse): PaperSections | null {
  if (project.sections) {
    return project.sections;
  }

  if (!project.generated_paper) {
    return null;
  }

  return {
    abstract: project.generated_paper.abstract,
    introduction: project.generated_paper.introduction,
    methodology: project.generated_paper.methodology,
    conclusion: project.generated_paper.conclusion,
  };
}

function syncProjectAfterSave(
  project: ProjectResponse,
  sections: PaperSections,
  updatedAt: string,
): ProjectResponse {
  return {
    ...project,
    edited_sections: sections,
    sections,
    updated_at: updatedAt,
    generated_paper: project.generated_paper
      ? {
          ...project.generated_paper,
          ...sections,
          formatted_paper: buildExportDocument(
            project.file_name.replace(/\.[^/.]+$/, ""),
            sections,
            project.generated_paper.references,
          ),
        }
      : project.generated_paper,
  };
}

function buildExportDocument(
  title: string,
  sections: PaperSections,
  references: string[],
) {
  const lines = [title, "", "Abstract", sections.abstract, "", "Introduction", sections.introduction, "", "Methodology", sections.methodology, "", "Conclusion", sections.conclusion, "", "References"];

  if (references.length === 0) {
    lines.push("No references available.");
  } else {
    lines.push(...references);
  }

  return lines.join("\n").trim();
}

function formatDuration(durationMs: number) {
  if (durationMs >= 1000) {
    return `${(durationMs / 1000).toFixed(1)}s`;
  }

  return `${Math.round(durationMs)}ms`;
}

function formatSavedAt(updatedAt: string | null) {
  if (!updatedAt) {
    return "Not saved yet";
  }

  const value = new Date(updatedAt);
  if (Number.isNaN(value.getTime())) {
    return "Saved";
  }

  return value.toLocaleString();
}

export default function EditorClientPage({
  projectId,
  title,
}: EditorClientPageProps) {
  const router = useRouter();
  const [editorState, setEditorState] = useState<EditorState>(() =>
    projectId
      ? { kind: "loading" }
      : {
          kind: "error",
          message:
            "Missing project ID. Start from the new project page to load a generated paper.",
        },
  );
  const [activeSection, setActiveSection] = useState<string>("abstract");
  const [sections, setSections] = useState<PaperSections | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    if (!projectId) {
      return () => controller.abort();
    }

    async function loadProject() {
      try {
        const project = await fetchProject(projectId, controller.signal);
        const projectSections = getProjectSections(project);

        if (!projectSections) {
          throw new Error(
            "This project has not finished generation yet. Return to processing or try again.",
          );
        }

        setSections(projectSections);
        setLastSavedAt(project.updated_at);
        setIsDirty(false);
        setSaveError(null);
        setEditorState({
          kind: "success",
          project,
          title: getProjectTitle(project, title),
        });
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }

        setEditorState({
          kind: "error",
          message:
            error instanceof Error
              ? error.message
              : "Unable to load the generated paper.",
        });
      }
    }

    void loadProject();

    return () => controller.abort();
  }, [projectId, title]);

  const sectionDescriptors = useMemo<SectionDescriptor[]>(() => {
    if (!sections) {
      return [];
    }

    const editableSections = editableSectionConfig.map((section) => ({
      id: section.id,
      title: section.title,
      content: sections[section.id],
      editable: true,
    }));

    if (editorState.kind !== "success") {
      return editableSections;
    }

    return [
      ...editableSections,
      {
        id: "references",
        title: "References",
        content: editorState.project.generated_paper?.references.join("\n") ?? "",
        editable: false,
      },
    ];
  }, [editorState, sections]);

  if (editorState.kind === "loading") {
    return (
      <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center">
        <div className="flex items-center gap-3 rounded-full border border-white/10 bg-black/30 px-5 py-3 text-white">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading generated paper...
        </div>
      </div>
    );
  }

  if (editorState.kind === "error") {
    return (
      <div className="mx-auto flex min-h-[calc(100vh-8rem)] max-w-2xl items-center justify-center px-4">
        <Card className="w-full border-rose-500/20 bg-rose-500/10 p-8 text-center shadow-none">
          <AlertCircle className="mx-auto mb-4 h-8 w-8 text-rose-300" />
          <h1 className="mb-3 text-2xl font-bold text-white">Unable to load editor</h1>
          <p className="mb-6 text-sm text-rose-100/90">{editorState.message}</p>
          <Button
            onClick={() => router.push("/new")}
            className="bg-white/10 text-white hover:bg-white/20"
          >
            Create New Project
          </Button>
        </Card>
      </div>
    );
  }

  const { project } = editorState;
  const resolvedTitle = editorState.title;
  const references = project.generated_paper?.references ?? [];
  const citationSources = project.generated_paper?.citation_sources ?? [];

  const handleSectionChange = (sectionId: EditableSectionKey, value: string) => {
    setSections((currentSections) => {
      if (!currentSections) {
        return currentSections;
      }

      return {
        ...currentSections,
        [sectionId]: value,
      };
    });
    setIsDirty(true);
    setSaveError(null);
  };

  const handleSave = async () => {
    if (!projectId || !sections || isSaving) {
      return;
    }

    setIsSaving(true);
    setSaveError(null);

    try {
      const response = await saveProjectSections(projectId, sections);
      const updatedProject = syncProjectAfterSave(
        project,
        response.sections,
        response.updated_at,
      );

      setSections(response.sections);
      setLastSavedAt(response.updated_at);
      setIsDirty(false);
      setEditorState({
        kind: "success",
        project: updatedProject,
        title: resolvedTitle,
      });
    } catch (error) {
      setSaveError(
        error instanceof Error ? error.message : "Unable to save your changes.",
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleExport = () => {
    if (!sections) {
      return;
    }

    const content = buildExportDocument(resolvedTitle, sections, references);
    const blob = new Blob([content], {
      type: "text/plain;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${resolvedTitle.replace(/\s+/g, "-").toLowerCase()}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const scrollToSection = (sectionId: string) => {
    setActiveSection(sectionId);
    document
      .getElementById(sectionId)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col animate-in fade-in duration-500 md:-mx-8">
      <div className="mt-0 flex items-center justify-between border-b border-white/10 bg-black/20 px-6 py-3 backdrop-blur-lg">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push("/new")}
            className="text-zinc-400 hover:bg-white/10 hover:text-white"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            New Project
          </Button>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-white drop-shadow-[0_0_8px_rgba(255,255,255,0.3)]">
              {resolvedTitle}
            </h1>
            <p className="text-xs text-indigo-200/70">
              Generated from {project.file_name} with {project.generation_metadata?.model}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Badge
            variant="outline"
            className={isDirty
              ? "border-amber-400/30 bg-amber-500/10 text-amber-100"
              : "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"}
          >
            <CheckCircle2 className="mr-1.5 h-3 w-3" />
            {isDirty ? "Unsaved changes" : "Saved state loaded"}
          </Badge>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={!isDirty || isSaving || !sections}
            className="border border-indigo-400/30 bg-indigo-600/80 text-white shadow-[0_0_15px_rgba(79,70,229,0.5)] hover:bg-indigo-500"
          >
            {isSaving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Save className="mr-2 h-4 w-4" />
                Save
              </>
            )}
          </Button>
          <Button
            size="sm"
            onClick={handleExport}
            className="border border-white/10 bg-white/10 text-white hover:bg-white/20"
          >
            <Download className="mr-2 h-4 w-4" />
            Export
          </Button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <ScrollArea className="flex-1 bg-transparent">
          <div className="mx-auto my-8 max-w-[840px] space-y-8 px-6 pb-16">
            <FloatingCard>
              <div className="space-y-4 rounded-2xl border border-white/10 bg-black/40 p-6 backdrop-blur-xl">
                <Badge className="border border-indigo-500/30 bg-indigo-500/15 text-indigo-100">
                  Editor Session
                </Badge>
                <div className="grid gap-4 md:grid-cols-4">
                  <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                    <p className="text-xs uppercase tracking-[0.24em] text-indigo-200/60">
                      Provider
                    </p>
                    <p className="mt-2 text-sm font-semibold text-white">
                      {project.generation_metadata?.provider ?? "vertex_ai"}
                    </p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                    <p className="text-xs uppercase tracking-[0.24em] text-indigo-200/60">
                      Total Time
                    </p>
                    <p className="mt-2 text-sm font-semibold text-white">
                      {project.generation_metadata
                        ? formatDuration(project.generation_metadata.generation_time_ms)
                        : "Unknown"}
                    </p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                    <p className="text-xs uppercase tracking-[0.24em] text-indigo-200/60">
                      Last Saved
                    </p>
                    <p className="mt-2 text-sm font-semibold text-white">
                      {formatSavedAt(lastSavedAt)}
                    </p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                    <p className="text-xs uppercase tracking-[0.24em] text-indigo-200/60">
                      Trace ID
                    </p>
                    <p className="mt-2 break-all text-sm font-semibold text-white">
                      {project.generation_metadata?.trace_id ?? "Unavailable"}
                    </p>
                  </div>
                </div>
                {saveError ? (
                  <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-100">
                    {saveError}
                  </div>
                ) : null}
              </div>
            </FloatingCard>

            {sectionDescriptors.map((section, index) => (
              <FloatingCard key={section.id} delay={index * 0.08}>
                <section
                  id={section.id}
                  className={`rounded-2xl border bg-black/40 p-8 backdrop-blur-xl transition-colors ${
                    activeSection === section.id
                      ? "border-indigo-400/40 shadow-[0_0_25px_rgba(79,70,229,0.18)]"
                      : "border-white/10"
                  }`}
                >
                  <div className="mb-5 flex items-center gap-3">
                    <div className="rounded-full border border-indigo-400/30 bg-indigo-500/15 p-2">
                      {section.id === "references" ? (
                        <Quote className="h-4 w-4 text-indigo-300" />
                      ) : (
                        <FileText className="h-4 w-4 text-indigo-300" />
                      )}
                    </div>
                    <h2 className="text-2xl font-bold tracking-tight text-white">
                      {section.title}
                    </h2>
                  </div>

                  {section.editable ? (
                    <Textarea
                      value={section.content}
                      onChange={(event) =>
                        handleSectionChange(
                          section.id as EditableSectionKey,
                          event.target.value,
                        )
                      }
                      className="min-h-[220px] resize-y border-white/10 bg-white/5 font-serif text-[1.02rem] leading-8 text-zinc-100 focus-visible:border-indigo-400/50 focus-visible:ring-indigo-400/20"
                    />
                  ) : (
                    <div className="space-y-3 text-sm leading-7 text-indigo-100/90">
                      {references.map((reference) => (
                        <p key={reference}>{reference}</p>
                      ))}
                    </div>
                  )}
                </section>
              </FloatingCard>
            ))}
          </div>
        </ScrollArea>

        <div className="hidden w-80 border-l border-white/10 bg-black/40 shadow-[-10px_0_30px_rgba(0,0,0,0.5)] backdrop-blur-xl xl:flex xl:flex-col">
          <Tabs defaultValue="outline" className="flex h-full flex-1 flex-col">
            <div className="border-b border-white/10 px-4 pt-4 pb-2">
              <TabsList className="grid w-full grid-cols-2 border border-white/10 bg-white/5">
                <TabsTrigger
                  value="outline"
                  className="text-xs font-semibold text-zinc-400 data-[state=active]:bg-indigo-600/80 data-[state=active]:text-white"
                >
                  Outline
                </TabsTrigger>
                <TabsTrigger
                  value="metadata"
                  className="text-xs font-semibold text-zinc-400 data-[state=active]:bg-indigo-600/80 data-[state=active]:text-white"
                >
                  Metadata
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="outline" className="m-0 flex-1 overflow-hidden p-0">
              <ScrollArea className="h-full">
                <div className="space-y-1 p-4">
                  <h4 className="mb-3 px-2 text-xs font-bold uppercase tracking-wider text-zinc-500">
                    Document Structure
                  </h4>
                  {sectionDescriptors.map((section) => (
                    <button
                      key={section.id}
                      onClick={() => scrollToSection(section.id)}
                      className={`flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-all ${
                        activeSection === section.id
                          ? "bg-indigo-500/20 font-semibold text-indigo-200 ring-1 ring-indigo-500/50"
                          : "font-medium text-zinc-400 hover:bg-white/5 hover:text-white"
                      }`}
                    >
                      <span>{section.title}</span>
                      <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                    </button>
                  ))}
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="metadata" className="m-0 flex-1 overflow-hidden p-0">
              <ScrollArea className="h-full">
                <div className="space-y-6 p-4">
                  <div>
                    <h4 className="mb-3 text-xs font-bold uppercase tracking-wider text-zinc-500">
                      Agent Timings
                    </h4>
                    <div className="space-y-3">
                      {project.generation_metadata?.agent_timings.map((timing) => (
                        <Card
                          key={timing.agent}
                          className="border-white/10 bg-white/5 p-3 shadow-none"
                        >
                          <p className="text-sm font-semibold text-white">
                            {timing.agent}
                          </p>
                          <p className="mt-1 text-xs text-indigo-200/70">
                            {formatDuration(timing.duration_ms)}
                          </p>
                        </Card>
                      ))}
                    </div>
                  </div>

                  <div>
                    <h4 className="mb-3 text-xs font-bold uppercase tracking-wider text-zinc-500">
                      Citation Sources
                    </h4>
                    <div className="space-y-3">
                      {citationSources.map((source) => (
                        <Card
                          key={source.ieee_reference}
                          className="border-white/10 bg-white/5 p-3 shadow-none"
                        >
                          <p className="text-sm font-semibold text-white">
                            {source.title}
                          </p>
                          <p className="mt-1 text-xs text-indigo-200/70">
                            {source.source}
                            {source.year ? `, ${source.year}` : ""}
                          </p>
                        </Card>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/10 p-4">
                    <div className="mb-2 flex items-center gap-2 text-indigo-100">
                      <Sparkles className="h-4 w-4" />
                      <p className="text-sm font-semibold">Live editor save system</p>
                    </div>
                    <p className="text-xs leading-6 text-indigo-100/75">
                      The editor loads the latest saved sections from the FastAPI
                      project store and persists changes through the `/save` endpoint.
                    </p>
                  </div>
                </div>
              </ScrollArea>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
