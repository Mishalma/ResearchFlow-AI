"use client";

import { type MouseEvent, useCallback, useState } from "react";
import { type FileRejection, useDropzone } from "react-dropzone";
import { AlertCircle, CheckCircle2, File, UploadCloud, X } from "lucide-react";

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
        className={`rounded-2xl border-2 border-dashed p-6 transition-colors ${
          error
            ? "border-red-300 bg-red-50"
            : isDragActive
              ? "border-indigo-400 bg-indigo-50"
              : "border-zinc-300 bg-zinc-50 hover:border-indigo-300 hover:bg-zinc-100"
        }`}
      >
        <input {...getInputProps()} />

        {!file ? (
          <div className="flex min-h-44 flex-col items-center justify-center text-center">
            <div className="mb-4 rounded-full border border-zinc-200 bg-white p-4 shadow-sm">
              {error ? (
                <AlertCircle className="h-8 w-8 text-red-500" />
              ) : (
                <UploadCloud className="h-8 w-8 text-indigo-500" />
              )}
            </div>

            <p className="text-lg font-semibold text-zinc-900">
              {isDragActive ? "Drop your file here" : "Drag and drop your file here"}
            </p>
            <p className="mt-2 max-w-md text-sm text-zinc-500">
              {error || "Choose a PDF or DOCX file up to 10MB."}
            </p>

            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                open();
              }}
              className="mt-5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500"
            >
              Select Source Document
            </button>
          </div>
        ) : (
          <div className="flex items-start gap-4">
            <div className="rounded-xl bg-indigo-100 p-3">
              <File className="h-7 w-7 text-indigo-600" />
            </div>

            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-zinc-900" title={file.name}>
                {file.name}
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {formatFileSize(file.size)} -{" "}
                {file.type.split("/").pop()?.toUpperCase() || "FILE"}
              </p>
              <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
                <CheckCircle2 className="h-4 w-4" />
                Ready for processing
              </div>
            </div>

            <button
              type="button"
              onClick={removeFile}
              className="rounded-md p-2 text-zinc-400 transition-colors hover:bg-zinc-200 hover:text-zinc-700"
              aria-label="Remove selected file"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>

      <p className="text-xs text-zinc-500">
        Accepted formats: PDF and DOCX. Maximum file size: 10MB.
      </p>
    </div>
  );
}

