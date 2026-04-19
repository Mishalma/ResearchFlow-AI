"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Download,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { IeeeManuscriptPreview } from "@/components/editor/ieee-manuscript-preview";
import {
  buildFigureAssetUrl,
  downloadBlob,
  exportProjectDocument,
  fetchProject,
  fetchProjects,
  saveProject,
  uploadProjectFigure,
  type ExportFormat,
  type FigureSection,
  type ProjectResponse,
} from "@/lib/backend";
import { parseIeeeManuscript } from "@/lib/ieee-manuscript";

const FIGURE_SECTION_OPTIONS: Array<{
  value: FigureSection;
  label: string;
}> = [
  { value: "introduction", label: "Introduction" },
  { value: "related_work", label: "Related Work" },
  { value: "methodology", label: "Methodology" },
  { value: "results", label: "Results" },
  { value: "discussion", label: "Discussion" },
  { value: "limitations", label: "Limitations" },
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

VI. LIMITATIONS
Write the limitations here.

VII. CONCLUSION
Write the conclusion here.

References
[1] Add references here.`;

type EditorClientPageProps = {
  projectId: string | null;
  title: string | null;
};

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
  const [manuscriptView, setManuscriptView] = useState<"preview" | "editor">(
    "preview",
  );
  const [isProjectLoading, setIsProjectLoading] = useState(Boolean(projectId));
  const [isSaving, setIsSaving] = useState(false);
  const [isUploadingFigure, setIsUploadingFigure] = useState(false);
  const [exportingFormat, setExportingFormat] = useState<ExportFormat | null>(
    null,
  );
  const [isDirty, setIsDirty] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [figureError, setFigureError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const refreshProjects = useCallback(async (signal?: AbortSignal) => {
    return fetchProjects(signal);
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
            : "Unable to load your paper right now.",
        );
        resetToBlankDraft(title);
        setIsProjectLoading(false);
      }
    }

    void initializeEditor();

    return () => controller.abort();
  }, [loadProjectById, projectId, refreshProjects, title]);

  const markDirty = () => {
    setIsDirty(true);
    setSaveError(null);
    setFigureError(null);
    setExportError(null);
  };

  const manuscriptPreview = useMemo(
    () =>
      parseIeeeManuscript(
        manuscriptValue,
        currentProject?.paper?.keywords ?? [],
      ),
    [currentProject?.paper?.keywords, manuscriptValue],
  );
  const authorLines = useMemo(() => textToAuthors(authorsValue), [authorsValue]);
  const generatedFigureCards = currentProject?.generated_figures ?? [];
  const generatedTableCards = currentProject?.generated_tables ?? [];

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

  const handleExport = async (format: ExportFormat) => {
    setExportError(null);

    let targetProject = currentProject;

    try {
      if (isDirty || !targetProject || !selectedProjectId) {
        targetProject = await persistCurrentProject();
      }

      if (!targetProject) {
        throw new Error("Save the paper before downloading it.");
      }

      setExportingFormat(format);
      const exportResult = await exportProjectDocument(targetProject.id, format);
      downloadBlob(exportResult.blob, exportResult.fileName);
    } catch (error) {
      setExportError(
        error instanceof Error
          ? error.message
          : "Unable to prepare this download right now.",
      );
    } finally {
      setExportingFormat(null);
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
              Review the complete IEEE paper, switch to an IEEE-style preview,
              export downloads, and attach figures.
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

          {(["pdf", "docx", "latex"] as ExportFormat[]).map((format) => (
            <Button
              key={format}
              size="sm"
              variant="ghost"
              onClick={() => void handleExport(format)}
              disabled={isSaving || exportingFormat !== null}
              className="border border-white/10 bg-white/5 text-white hover:bg-white/10"
            >
              {exportingFormat === format ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Preparing {format.toUpperCase()}
                </>
              ) : (
                <>
                  <Download className="mr-2 h-4 w-4" />
                  {format.toUpperCase()}
                </>
              )}
            </Button>
          ))}
        </div>
      </div>

      <div className="grid flex-1 gap-6 px-4 pb-8 md:px-6 xl:grid-cols-[minmax(0,1.45fr)_320px] 2xl:grid-cols-[minmax(0,1.6fr)_340px]">
        <div className="space-y-6">
          {pageError ? (
            <Card className="border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-100 shadow-none">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 text-rose-300" />
                <p>{pageError}</p>
              </div>
            </Card>
          ) : null}

          {exportError ? (
            <Card className="border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-100 shadow-none">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 text-rose-300" />
                <p>{exportError}</p>
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
              Preview the manuscript in an IEEE-style two-column layout, then
              switch back to source editing whenever you need to adjust the raw
              headings and content.
            </p>
            <Tabs
              value={manuscriptView}
              onValueChange={(value) =>
                setManuscriptView(value as "preview" | "editor")
              }
              className="gap-4"
            >
              <TabsList
                variant="line"
                className="rounded-xl border border-white/10 bg-white/5 p-1"
              >
                <TabsTrigger
                  value="preview"
                  className="rounded-lg px-4 text-zinc-300 data-active:text-white"
                >
                  IEEE Preview
                </TabsTrigger>
                <TabsTrigger
                  value="editor"
                  className="rounded-lg px-4 text-zinc-300 data-active:text-white"
                >
                  Source Editor
                </TabsTrigger>
              </TabsList>

              <TabsContent value="preview" className="space-y-4">
                <div className="rounded-2xl border border-indigo-400/20 bg-indigo-500/10 px-4 py-3 text-sm text-indigo-100">
                  This preview follows an IEEE conference-style reading surface:
                  two columns, single-spaced body copy, and Times-style 10pt
                  typography. Use the download buttons above for PDF, DOCX, or
                  LaTeX exports.
                </div>
                <IeeeManuscriptPreview
                  title={titleValue}
                  authors={authorLines}
                  preview={manuscriptPreview}
                  figures={currentProject?.figures ?? []}
                  generatedFigures={generatedFigureCards}
                  generatedTables={generatedTableCards}
                  projectId={currentProject?.id ?? null}
                />
              </TabsContent>

              <TabsContent value="editor" className="space-y-4">
                <div className="text-sm text-indigo-200/70">
                  Keep the headings like
                  <span className="mx-1 font-semibold text-indigo-100">
                    Abstract
                  </span>
                  ,
                  <span className="mx-1 font-semibold text-indigo-100">
                    Index Terms
                  </span>
                  , and the numbered section titles intact so the backend can
                  save the paper correctly.
                </div>
                <Textarea
                  value={manuscriptValue}
                  onChange={(event) => {
                    setManuscriptValue(event.target.value);
                    markDirty();
                  }}
                  placeholder="The generated paper will appear here..."
                  className="min-h-[640px] resize-y border-white/10 bg-white/5 font-serif leading-8 text-zinc-100 placeholder:text-zinc-500"
                />
              </TabsContent>
            </Tabs>
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
            {generatedFigureCards.length || generatedTableCards.length ? (
              <>
                {generatedFigureCards.map((figure) => (
                  <div
                    key={figure.spec.id}
                    className="overflow-hidden rounded-2xl border border-emerald-400/20 bg-emerald-500/5"
                  >
                    {figure.png_base64 ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={`data:image/png;base64,${figure.png_base64}`}
                        alt={figure.spec.caption}
                        className="h-36 w-full object-contain bg-white/80"
                      />
                    ) : null}
                    <div className="space-y-1 p-3">
                      <p className="text-xs uppercase tracking-[0.2em] text-emerald-200/70">
                        Generated figure
                      </p>
                      <p className="text-sm font-semibold text-white">
                        {figure.spec.caption}
                      </p>
                      <p className="text-xs uppercase tracking-[0.2em] text-indigo-200/60">
                        Attached to {figure.spec.section.replace("_", " ")}
                      </p>
                    </div>
                  </div>
                ))}

                {generatedTableCards.map((table) => (
                  <div
                    key={table.spec.id}
                    className="overflow-hidden rounded-2xl border border-sky-400/20 bg-sky-500/5 p-3"
                  >
                    <p className="text-xs uppercase tracking-[0.2em] text-sky-200/70">
                      Generated table
                    </p>
                    <p className="mt-1 text-sm font-semibold text-white">
                      {table.spec.caption}
                    </p>
                    <p className="mt-1 text-xs uppercase tracking-[0.2em] text-indigo-200/60">
                      Attached to {table.spec.section.replace("_", " ")}
                    </p>
                  </div>
                ))}
              </>
            ) : null}

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
                {generatedFigureCards.length || generatedTableCards.length
                  ? "No uploaded figures attached yet."
                  : "No figures attached yet."}
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

