"use client";

import React, { useCallback, useState } from "react";
import { useDropzone, FileRejection } from "react-dropzone";
import { UploadCloud, File, X, CheckCircle2, AlertCircle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";

interface FileUploadProps {
  onFileSelect: (file: File | null) => void;
  accept?: Record<string, string[]>;
  maxSize?: number; // in bytes
}

export function FileUpload({
  onFileSelect,
  accept = {
    "application/pdf": [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  },
  maxSize = 10485760, // 10MB
}: FileUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState<"idle" | "uploading" | "success" | "error">("idle");

  const onDrop = useCallback(
    (acceptedFiles: File[], fileRejections: FileRejection[]) => {
      setError(null);
      setProgress(0);

      if (fileRejections.length > 0) {
        const rejection = fileRejections[0];
        if (rejection.errors[0]?.code === "file-too-large") {
          setError(`File is too large. Max size is ${Math.round(maxSize / 1024 / 1024)}MB`);
        } else if (rejection.errors[0]?.code === "file-invalid-type") {
          setError("Invalid file type. Please upload a PDF or DOCX.");
        } else {
          setError(rejection.errors[0]?.message || "Failed to upload file.");
        }
        return;
      }

      if (acceptedFiles.length > 0) {
        const selectedFile = acceptedFiles[0];
        setFile(selectedFile);
        setUploadStatus("uploading");
        onFileSelect(selectedFile);

        // Simulate upload progress
        let currentProgress = 0;
        const interval = setInterval(() => {
          currentProgress += Math.random() * 20 + 10;
          if (currentProgress >= 100) {
            currentProgress = 100;
            clearInterval(interval);
            setUploadStatus("success");
          }
          setProgress(Math.min(currentProgress, 100));
        }, 300);
      }
    },
    [maxSize, onFileSelect]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept,
    maxSize,
    multiple: false,
  });

  const removeFile = (e: React.MouseEvent) => {
    e.stopPropagation();
    setFile(null);
    setProgress(0);
    setUploadStatus("idle");
    setError(null);
    onFileSelect(null);
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  return (
    <div className="w-full">
      <AnimatePresence mode="wait">
        {!file && (
          <motion.div
            key="dropzone"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            {...(getRootProps() as any)}
            className={`relative border-2 border-dashed rounded-xl p-10 flex flex-col items-center justify-center text-center cursor-pointer transition-colors
              ${
                isDragActive
                  ? "border-indigo-500 bg-indigo-50"
                  : error
                  ? "border-red-300 bg-red-50 hover:bg-red-50/80"
                  : "border-zinc-300 bg-zinc-50 hover:bg-zinc-100 hover:border-indigo-300"
              }
            `}
          >
            <input {...getInputProps()} />
            
            <div className={`p-4 rounded-full mb-4 ${isDragActive ? "bg-indigo-100" : error ? "bg-red-100" : "bg-white shadow-sm border border-zinc-200"}`}>
              {error ? (
                <AlertCircle className="w-8 h-8 text-red-500" />
              ) : (
                <UploadCloud className={`w-8 h-8 ${isDragActive ? "text-indigo-600" : "text-zinc-500"}`} />
              )}
            </div>

            <h3 className="text-lg font-semibold text-zinc-900 mb-2">
              {isDragActive ? "Drop file to upload" : "Click or drag to upload"}
            </h3>
            
            <p className="text-sm text-zinc-500 max-w-xs mb-4">
              {error || "Supports PDF, DOCX up to 10MB."}
            </p>

            <Button type="button" variant="outline" className="bg-white pointer-events-none">
              Select File
            </Button>
          </motion.div>
        )}

        {file && (
          <motion.div
            key="file-preview"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="border border-zinc-200 rounded-xl p-6 bg-white shadow-sm relative overflow-hidden"
          >
            <div className="flex items-start gap-4">
              <div className="p-3 bg-indigo-50 rounded-lg shrink-0">
                <File className="w-8 h-8 text-indigo-500" />
              </div>
              
              <div className="flex-1 min-w-0 pr-8">
                <p className="text-sm font-semibold text-zinc-900 truncate mb-1" title={file.name}>
                  {file.name}
                </p>
                <div className="flex items-center gap-3 text-xs text-zinc-500 mb-3">
                  <span>{formatFileSize(file.size)}</span>
                  <span>•</span>
                  <span>{file.type.split("/").pop()?.toUpperCase() || "FILE"}</span>
                </div>

                {uploadStatus === "uploading" && (
                  <div className="space-y-2">
                    <div className="flex justify-between text-xs font-medium text-indigo-600">
                      <span>Uploading...</span>
                      <span>{Math.round(progress)}%</span>
                    </div>
                    <Progress value={progress} className="h-2 bg-indigo-100 [&>div]:bg-indigo-500" />
                  </div>
                )}
                
                {uploadStatus === "success" && (
                  <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-600">
                    <CheckCircle2 className="w-4 h-4" /> Ready for processing
                  </div>
                )}
              </div>
            </div>

            <button
              onClick={removeFile}
              className="absolute top-4 right-4 p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 rounded-md transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
