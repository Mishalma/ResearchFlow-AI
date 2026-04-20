"use client";

import { type MouseEvent, useCallback, useState } from "react";
import { type FileRejection, useDropzone } from "react-dropzone";
import {
  AlertCircle,
  CheckCircle2,
  File,
  FileBadge2,
  Sparkles,
  UploadCloud,
  X,
} from "lucide-react";

interface FileUploadProps {
  onFileSelect: (file: File | null) => void;
  accept?: Record<string, string[]>;
  maxSize?: number;
}

const DEFAULT_ACCEPT = {
  "application/pdf": [".pdf"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
    ".docx",
  ],
};

export function FileUpload({
  onFileSelect,
  accept = DEFAULT_ACCEPT,
  maxSize = 10 * 1024 * 1024,
}: FileUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onDrop = useCallback(
    (acceptedFiles: File[], fileRejections: FileRejection[]) => {
      setError(null);

      if (fileRejections.length > 0) {
        const rejection = fileRejections[0];
        const firstError = rejection.errors[0];

        if (firstError?.code === "file-too-large") {
          setError(
            `File is too large. Maximum allowed size is ${Math.round(
              maxSize / 1024 / 1024,
            )}MB.`,
          );
        } else if (firstError?.code === "file-invalid-type") {
          setError("Invalid file type. Please upload a PDF or DOCX file.");
        } else {
          setError(firstError?.message || "Unable to select this file.");
        }

        setFile(null);
        onFileSelect(null);
        return;
      }

      const selectedFile = acceptedFiles[0] ?? null;
      setFile(selectedFile);
      onFileSelect(selectedFile);
    },
    [maxSize, onFileSelect],
  );

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    accept,
    maxSize,
    multiple: false,
    noKeyboard: true,
  });

  const removeFile = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setFile(null);
    setError(null);
    onFileSelect(null);
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return "0 Bytes";

    const units = ["Bytes", "KB", "MB", "GB"];
    const unitIndex = Math.floor(Math.log(bytes) / Math.log(1024));
    const value = bytes / 1024 ** unitIndex;

    return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
  };

  return (
    <div className="w-full space-y-3">
      <div
        {...getRootProps()}
        className={`group relative overflow-hidden rounded-[28px] border p-6 transition-all duration-200 sm:p-7 ${
          error
            ? "border-rose-500/30 bg-[linear-gradient(180deg,rgba(58,17,29,0.92)_0%,rgba(24,8,14,0.98)_100%)] shadow-[0_0_0_1px_rgba(244,63,94,0.08)]"
            : isDragActive
              ? "border-indigo-400/50 bg-[linear-gradient(180deg,rgba(31,41,105,0.9)_0%,rgba(12,16,34,0.98)_100%)] shadow-[0_24px_80px_-48px_rgba(99,102,241,0.9)]"
              : "border-white/10 bg-[linear-gradient(180deg,rgba(20,23,33,0.96)_0%,rgba(10,12,19,0.98)_100%)] shadow-[0_24px_80px_-54px_rgba(15,23,42,0.95)] hover:border-indigo-300/25 hover:bg-[linear-gradient(180deg,rgba(24,28,43,0.98)_0%,rgba(12,15,25,0.98)_100%)]"
        }`}
      >
        <input {...getInputProps()} />
        <div
          aria-hidden
          className={`pointer-events-none absolute inset-x-8 top-0 h-24 rounded-b-[999px] blur-3xl transition-opacity ${
            error
              ? "bg-rose-500/14 opacity-100"
              : isDragActive
                ? "bg-indigo-400/22 opacity-100"
                : "bg-sky-400/8 opacity-70 group-hover:opacity-100"
          }`}
        />

        {!file ? (
          <div className="relative flex min-h-[18rem] flex-col items-center justify-center text-center">
            <div
              className={`mb-5 flex h-[4.5rem] w-[4.5rem] items-center justify-center rounded-full border shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] ${
                error
                  ? "border-rose-400/30 bg-rose-500/12"
                  : isDragActive
                    ? "border-indigo-300/40 bg-indigo-500/14"
                    : "border-white/10 bg-white/[0.06]"
              }`}
            >
              {error ? (
                <AlertCircle className="h-8 w-8 text-rose-300" />
              ) : (
                <UploadCloud
                  className={`h-8 w-8 ${
                    isDragActive ? "text-indigo-200" : "text-indigo-300"
                  }`}
                />
              )}
            </div>

            <p className="text-xl font-semibold tracking-tight text-white">
              {isDragActive ? "Drop your file here" : "Drag and drop your file here"}
            </p>
            <p className="mt-2 max-w-md text-sm leading-6 text-slate-300/72">
              {error || "Choose a PDF or DOCX manuscript up to 10MB to start the live processing workflow."}
            </p>

            <div className="mt-6 flex flex-col items-center gap-4">
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  open();
                }}
                className="inline-flex h-11 items-center justify-center rounded-2xl border border-indigo-300/15 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 px-5 text-sm font-semibold text-white shadow-[0_0_28px_rgba(59,130,246,0.22)] transition-all hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400"
              >
                Select Source Document
              </button>

              <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-slate-400/80">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-white/8 bg-white/[0.04] px-3 py-1.5">
                  <FileBadge2 className="h-3.5 w-3.5 text-indigo-300" />
                  PDF or DOCX
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-white/8 bg-white/[0.04] px-3 py-1.5">
                  <Sparkles className="h-3.5 w-3.5 text-sky-300" />
                  Maximum 10MB
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="relative flex flex-col gap-4 sm:flex-row sm:items-start">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-indigo-300/14 bg-indigo-500/12 text-indigo-200">
              <File className="h-6 w-6" />
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="truncate text-base font-semibold text-white" title={file.name}>
                  {file.name}
                </p>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/18 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-200">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Ready for processing
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-300/68">
                Source document attached successfully.
              </p>
              <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-300/74">
                <span className="rounded-full border border-white/8 bg-white/4 px-3 py-1.5">
                  {formatFileSize(file.size)}
                </span>
                <span className="rounded-full border border-white/8 bg-white/4 px-3 py-1.5">
                  {file.type.split("/").pop()?.toUpperCase() || "FILE"}
                </span>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  open();
                }}
                className="inline-flex h-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] px-4 text-sm font-medium text-white transition-colors hover:bg-white/10"
              >
                Replace
              </button>
              <button
                type="button"
                onClick={removeFile}
                className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
                aria-label="Remove selected file"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400/78">
        <span className="rounded-full border border-white/8 bg-white/[0.04] px-3 py-1.5">
          Accepted formats: PDF and DOCX
        </span>
        <span className="rounded-full border border-white/8 bg-white/[0.04] px-3 py-1.5">
          Maximum file size: 10MB
        </span>
      </div>
    </div>
  );
}

