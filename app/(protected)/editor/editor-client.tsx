"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  FileImage,
  FileText,
  Loader2,
  Plus,
  Save,
  Upload,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  buildFigureAssetUrl,
  fetchProject,
  fetchProjects,
  saveProject,
  uploadProjectFigure,
  type FigureSection,
  type ProjectResponse,
  type ProjectSummary,
} from "@/lib/backend";

const FIGURE_SECTION_OPTIONS: Array<{
  value: FigureSection;
  label: string;
}> = [
  { value: "introduction", label: "Introduction" },
  { value: "related_work", label: "Related Work" },
  { value: "methodology", label: "Methodology" },
  { value: "results", label: "Results" },
  { value: "discussion", label: "Discussion" },
  { value: "conclusion", label: "Conclusion" },
];

const EMPTY_MANUSCRIPT_TEMPLATE = `Abstract
Write the abstract here.

Index Terms - keyword one, keyword two

I. INTRODUCTION
Write the introduction here.

II. RELATED WORK
Write the related work section here.

III. METHODOLOGY
Write the methodology here.

IV. RESULTS
Write the results here.

V. DISCUSSION
Write the discussion here.

VI. CONCLUSION
Write the conclusion here.

References
[1] Add references here.`;

type EditorClientPageProps = {
  projectId: string | null;
  title: string | null;
};

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "Recently updated";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Recently updated";
  }

  return parsed.toLocaleDateString();
}

function authorsToText(authors: string[]) {
  return authors.join("\n");
}

function textToAuthors(value: string) {
  return value
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export default function EditorClientPage({
  projectId,
  title,
}: EditorClientPageProps) {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [currentProject, setCurrentProject] = useState<ProjectResponse | null>(
    null,
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    projectId,
  );
  const [titleValue, setTitleValue] = useState(title?.trim() ?? "");
  const [authorsValue, setAuthorsValue] = useState("");
  const [manuscriptValue, setManuscriptValue] = useState(EMPTY_MANUSCRIPT_TEMPLATE);
  const [figureFile, setFigureFile] = useState<File | null>(null);
  const [figureCaption, setFigureCaption] = useState("");
  const [figureSection, setFigureSection] =
    useState<FigureSection>("methodology");
  const [isProjectsLoading, setIsProjectsLoading] = useState(true);
  const [isProjectLoading, setIsProjectLoading] = useState(Boolean(projectId));
  const [isSaving, setIsSaving] = useState(false);
  const [isUploadingFigure, setIsUploadingFigure] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [figureError, setFigureError] = useState<string | null>(null);

  const refreshProjects = useCallback(async (signal?: AbortSignal) => {
    const projectList = await fetchProjects(signal);
    setProjects(projectList);
    return projectList;
  }, []);

  const applyProject = useCallback((project: ProjectResponse) => {
    setCurrentProject(project);
    setSelectedProjectId(project.id);
    setTitleValue(project.title);
    setAuthorsValue(authorsToText(project.authors));
    setManuscriptValue(project.display_paper_text || EMPTY_MANUSCRIPT_TEMPLATE);
    setIsDirty(false);
    setSaveError(null);
    setFigureError(null);
  }, []);

  function resetToBlankDraft(seedTitle?: string | null) {
    setCurrentProject(null);
    setSelectedProjectId(null);
    setTitleValue(seedTitle?.trim() ?? "Untitled Research Paper");
    setAuthorsValue("");
    setManuscriptValue(EMPTY_MANUSCRIPT_TEMPLATE);
    setFigureFile(null);
    setFigureCaption("");
    setFigureSection("methodology");
    setIsDirty(false);
    setPageError(null);
    setSaveError(null);
    setFigureError(null);
  }

  const loadProjectById = useCallback(
    async (
      id: string,
      signal?: AbortSignal,
      options?: { updateUrl?: boolean },
    ) => {
      setIsProjectLoading(true);
      setPageError(null);

      try {
        const project = await fetchProject(id, signal);

        if (signal?.aborted) {
          return;
        }

        applyProject(project);

        if (options?.updateUrl !== false) {
          router.replace(`/editor?projectId=${project.id}`);
        }
      } catch (error) {
        if (signal?.aborted) {
          return;
        }

        setPageError(
          error instanceof Error ? error.message : "Unable to load this paper.",
        );
      } finally {
        if (!signal?.aborted) {
          setIsProjectLoading(false);
        }
      }
    },
    [applyProject, router],
  );

  useEffect(() => {
    const controller = new AbortController();

    async function initializeEditor() {
      setIsProjectsLoading(true);

      try {
        const projectList = await refreshProjects(controller.signal);
        const targetProjectId = projectId ?? projectList[0]?.id ?? null;

        if (targetProjectId) {
          await loadProjectById(targetProjectId, controller.signal, {
            updateUrl: false,
          });
        } else {
          resetToBlankDraft(title);
          setIsProjectLoading(false);
        }
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }

        setPageError(
          error instanceof Error
            ? error.message
            : "Unable to load saved papers right now.",
        );
        resetToBlankDraft(title);
        setIsProjectLoading(false);
      } finally {
        if (!controller.signal.aborted) {
          setIsProjectsLoading(false);
        }
      }
    }

    void initializeEditor();

    return () => controller.abort();
  }, [loadProjectById, projectId, refreshProjects, title]);

  const markDirty = () => {
    setIsDirty(true);
    setSaveError(null);
    setFigureError(null);
  };

  const persistCurrentProject = useCallback(async () => {
    const normalizedTitle = titleValue.trim();
    const normalizedContent = manuscriptValue.trim();

    if (!normalizedTitle) {
      throw new Error("Paper title is required.");
    }

    if (!normalizedContent) {
      throw new Error("Paper content is required.");
    }

    setIsSaving(true);
    setSaveError(null);

    try {
      const response = await saveProject({
        project_id: selectedProjectId ?? undefined,
        title: normalizedTitle,
        authors: textToAuthors(authorsValue),
        content: normalizedContent,
      });

      applyProject(response.project);
      await refreshProjects();
      router.replace(`/editor?projectId=${response.project.id}`);
      return response.project;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unable to save this paper.";
      setSaveError(message);
      throw new Error(message);
    } finally {
      setIsSaving(false);
    }
  }, [
    applyProject,
    authorsValue,
    manuscriptValue,
    refreshProjects,
    router,
    selectedProjectId,
    titleValue,
  ]);

  const handleSave = async () => {
    try {
      await persistCurrentProject();
    } catch {
      // Save errors are already rendered inline.
    }
  };

  const handleFigureUpload = async () => {
    setFigureError(null);

    if (!figureFile) {
      setFigureError("Choose a PNG or JPG figure to upload.");
      return;
    }

    if (!figureCaption.trim()) {
      setFigureError("Figure caption is required.");
      return;
    }

    let targetProject = currentProject;

    try {
      if (isDirty || !targetProject || !selectedProjectId) {
        targetProject = await persistCurrentProject();
      }

      if (!targetProject) {
        throw new Error("Save the paper before uploading figures.");
      }

      setIsUploadingFigure(true);
      await uploadProjectFigure({
        projectId: targetProject.id,
        caption: figureCaption.trim(),
        section: figureSection,
        file: figureFile,
      });

      const refreshedProject = await fetchProject(targetProject.id);
      applyProject(refreshedProject);
      await refreshProjects();
      setFigureFile(null);
      setFigureCaption("");
      setFigureSection("methodology");
    } catch (error) {
      setFigureError(
        error instanceof Error
          ? error.message
          : "Unable to upload this figure right now.",
      );
    } finally {
      setIsUploadingFigure(false);
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col gap-6 animate-in fade-in duration-500">
      <div className="flex flex-col gap-4 border-b border-white/10 bg-black/20 px-4 py-4 backdrop-blur-lg md:flex-row md:items-center md:justify-between md:px-6">
        <div className="flex items-center gap-3">
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
            <h1 className="text-2xl font-bold tracking-tight text-white">
              Paper Editor
            </h1>
            <p className="text-sm text-indigo-200/70">
              Review the complete IEEE paper, edit the manuscript, and attach
              figures.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Badge
            variant="outline"
            className={
              isDirty
                ? "border-amber-400/30 bg-amber-500/10 text-amber-100"
                : "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
            }
          >
            <CheckCircle2 className="mr-1.5 h-3 w-3" />
            {isDirty ? "Unsaved changes" : "Saved"}
          </Badge>

          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              resetToBlankDraft("Untitled Research Paper");
              router.replace("/editor");
            }}
            className="border border-white/10 bg-white/5 text-white hover:bg-white/10"
          >
            <Plus className="mr-2 h-4 w-4" />
            New Draft
          </Button>

          <Button
            size="sm"
            onClick={() => void handleSave()}
            disabled={isSaving}
            className="border border-indigo-400/30 bg-indigo-600/80 text-white hover:bg-indigo-500"
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
        </div>
      </div>

      <div className="grid flex-1 gap-6 px-4 pb-8 md:px-6 xl:grid-cols-[280px_minmax(0,1fr)_360px]">
        <Card className="border-white/10 bg-black/40 p-0 shadow-none backdrop-blur-xl">
          <div className="border-b border-white/10 px-5 py-4">
            <div className="flex items-center gap-2 text-white">
              <FileText className="h-4 w-4 text-indigo-300" />
              <h2 className="font-semibold">Saved Papers</h2>
            </div>
            <p className="mt-1 text-sm text-indigo-200/70">
              Open an existing paper or start a fresh draft.
            </p>
          </div>

          <ScrollArea className="h-[420px] xl:h-[calc(100vh-18rem)]">
            <div className="space-y-2 p-4">
              {isProjectsLoading ? (
                <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-4 text-sm text-zinc-300">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading saved papers...
                </div>
              ) : projects.length === 0 ? (
                <div className="rounded-xl border border-dashed border-white/10 bg-white/5 px-4 py-6 text-sm text-zinc-400">
                  No saved papers yet.
                </div>
              ) : (
                projects.map((project) => {
                  const isActive = selectedProjectId === project.id;

                  return (
                    <button
                      key={project.id}
                      type="button"
                      onClick={() => void loadProjectById(project.id)}
                      className={`w-full rounded-xl border px-4 py-3 text-left transition-all ${
                        isActive
                          ? "border-indigo-400/40 bg-indigo-500/15 text-white shadow-[0_0_18px_rgba(79,70,229,0.12)]"
                          : "border-white/10 bg-white/5 text-zinc-300 hover:border-white/20 hover:bg-white/10"
                      }`}
                    >
                      <p className="truncate text-sm font-semibold">
                        {project.title}
                      </p>
                      <p className="mt-1 text-xs text-indigo-200/65">
                        {formatDateTime(project.updated_at)}
                      </p>
                    </button>
                  );
                })
              )}
            </div>
          </ScrollArea>
        </Card>

        <div className="space-y-6">
          {pageError ? (
            <Card className="border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-100 shadow-none">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 text-rose-300" />
                <p>{pageError}</p>
              </div>
            </Card>
          ) : null}

          <Card className="border-white/10 bg-black/40 p-6 shadow-none backdrop-blur-xl">
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-semibold text-zinc-200">
                  Paper Title
                </label>
                <Input
                  value={titleValue}
                  onChange={(event) => {
                    setTitleValue(event.target.value);
                    markDirty();
                  }}
                  placeholder="Enter your research paper title"
                  className="border-white/10 bg-white/5 text-white placeholder:text-zinc-500"
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-semibold text-zinc-200">
                  Authors
                </label>
                <Textarea
                  value={authorsValue}
                  onChange={(event) => {
                    setAuthorsValue(event.target.value);
                    markDirty();
                  }}
                  placeholder="One author per line: Name, Affiliation"
                  className="min-h-[120px] border-white/10 bg-white/5 text-white placeholder:text-zinc-500"
                />
              </div>
            </div>
          </Card>

          <Card className="border-white/10 bg-black/40 p-6 shadow-none backdrop-blur-xl">
            <div className="mb-4 flex items-center gap-2 text-white">
              <FileText className="h-4 w-4 text-indigo-300" />
              <h2 className="font-semibold">Complete Paper</h2>
            </div>
            <p className="mb-4 text-sm text-indigo-200/70">
              Edit the full IEEE manuscript here. Keep the headings like
              <span className="mx-1 font-semibold text-indigo-100">
                Abstract
              </span>
              ,
              <span className="mx-1 font-semibold text-indigo-100">
                Index Terms
              </span>
              , and the numbered section titles intact so the backend can save
              the paper correctly.
            </p>
            <Textarea
              value={manuscriptValue}
              onChange={(event) => {
                setManuscriptValue(event.target.value);
                markDirty();
              }}
              placeholder="The generated paper will appear here..."
              className="min-h-[640px] resize-y border-white/10 bg-white/5 font-serif leading-8 text-zinc-100 placeholder:text-zinc-500"
            />
          </Card>

          {saveError ? (
            <Card className="border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-100 shadow-none">
              {saveError}
            </Card>
          ) : null}

          {isProjectLoading ? (
            <div className="flex items-center gap-2 text-sm text-indigo-200/70">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading paper content...
            </div>
          ) : null}
        </div>

        <Card className="border-white/10 bg-black/40 p-6 shadow-none backdrop-blur-xl">
          <div className="flex items-center gap-2 text-white">
            <FileImage className="h-4 w-4 text-indigo-300" />
            <h2 className="font-semibold">Figures</h2>
          </div>
          <p className="mt-1 text-sm text-indigo-200/70">
            Upload PNG or JPG figures and attach them to the relevant section of
            the paper.
          </p>

          <div className="mt-4 space-y-3">
            <Input
              type="file"
              accept=".png,.jpg,.jpeg,image/png,image/jpeg"
              onChange={(event) => setFigureFile(event.target.files?.[0] ?? null)}
              className="border-white/10 bg-white/5 text-white file:mr-4 file:rounded-md file:border-0 file:bg-indigo-600/80 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white"
            />

            <Input
              value={figureCaption}
              onChange={(event) => setFigureCaption(event.target.value)}
              placeholder="Figure caption"
              className="border-white/10 bg-white/5 text-white placeholder:text-zinc-500"
            />

            <select
              value={figureSection}
              onChange={(event) =>
                setFigureSection(event.target.value as FigureSection)
              }
              className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none"
            >
              {FIGURE_SECTION_OPTIONS.map((section) => (
                <option
                  key={section.value}
                  value={section.value}
                  className="bg-zinc-950"
                >
                  {section.label}
                </option>
              ))}
            </select>

            <Button
              onClick={() => void handleFigureUpload()}
              disabled={isUploadingFigure}
              className="w-full border border-white/10 bg-white/10 text-white hover:bg-white/20"
            >
              {isUploadingFigure ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Uploading figure...
                </>
              ) : (
                <>
                  <Upload className="mr-2 h-4 w-4" />
                  Upload Figure
                </>
              )}
            </Button>
          </div>

          {figureError ? (
            <div className="mt-4 rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-100">
              {figureError}
            </div>
          ) : null}

          <div className="mt-5 space-y-3">
            {currentProject?.figures.length ? (
              currentProject.figures.map((figure) => (
                <div
                  key={figure.id}
                  className="overflow-hidden rounded-2xl border border-white/10 bg-white/5"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={buildFigureAssetUrl(currentProject.id, figure.id)}
                    alt={figure.caption}
                    className="h-36 w-full object-cover"
                  />
                  <div className="space-y-1 p-3">
                    <p className="text-sm font-semibold text-white">
                      {figure.caption}
                    </p>
                    <p className="text-xs uppercase tracking-[0.2em] text-indigo-200/60">
                      Attached to {figure.section.replace("_", " ")}
                    </p>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-white/10 bg-white/5 px-4 py-6 text-sm text-zinc-400">
                No figures attached yet.
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

