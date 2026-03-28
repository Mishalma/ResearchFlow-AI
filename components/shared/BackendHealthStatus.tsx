"use client";

import { useEffect, useState } from "react";
import { AlertCircle, LoaderCircle, ServerCog } from "lucide-react";

import { FloatingCard } from "@/components/3d/FloatingCard";
import { Badge } from "@/components/ui/badge";
import {
  backendHealthEndpoint,
  fetchBackendHealth,
  type BackendHealthResponse,
} from "@/lib/backend";

type HealthState =
  | { kind: "loading" }
  | { kind: "success"; data: BackendHealthResponse }
  | { kind: "error"; message: string };

export function BackendHealthStatus() {
  const [healthState, setHealthState] = useState<HealthState>({
    kind: "loading",
  });

  useEffect(() => {
    const controller = new AbortController();

    async function loadHealthStatus() {
      try {
        const data = await fetchBackendHealth(controller.signal);
        console.info("Backend health check:", data);
        setHealthState({ kind: "success", data });
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }

        console.error("Backend health check failed:", error);
        setHealthState({
          kind: "error",
          message:
            error instanceof Error
              ? error.message
              : "Unable to connect to the backend.",
        });
      }
    }

    void loadHealthStatus();

    return () => {
      controller.abort();
    };
  }, []);

  const statusBadge =
    healthState.kind === "success"
      ? {
          label: "Connected",
          className:
            "border border-emerald-400/40 bg-emerald-500/15 text-emerald-200",
        }
      : healthState.kind === "error"
        ? {
            label: "Offline",
            className:
              "border border-rose-400/40 bg-rose-500/15 text-rose-200",
          }
        : {
            label: "Checking",
            className:
              "border border-amber-400/40 bg-amber-500/15 text-amber-100",
          };

  const statusMessage =
    healthState.kind === "success"
      ? healthState.data.message
      : healthState.kind === "error"
        ? healthState.message
        : "Waiting for the FastAPI backend to answer the health check.";

  return (
    <FloatingCard className="max-w-2xl">
      <div className="space-y-5 p-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="space-y-3">
            <Badge className="border border-indigo-400/30 bg-indigo-500/15 text-indigo-100">
              Backend Connection
            </Badge>
            <div>
              <h2 className="text-2xl font-bold tracking-tight text-white">
                FastAPI health check
              </h2>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-indigo-200/75">
                The Next.js frontend calls the local backend from the browser so
                we can verify the API and CORS configuration are working
                together.
              </p>
            </div>
          </div>

          <Badge className={statusBadge.className}>{statusBadge.label}</Badge>
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm">
          <div className="flex items-start gap-3">
            {healthState.kind === "success" ? (
              <ServerCog className="mt-0.5 h-5 w-5 text-emerald-300" />
            ) : healthState.kind === "error" ? (
              <AlertCircle className="mt-0.5 h-5 w-5 text-rose-300" />
            ) : (
              <LoaderCircle className="mt-0.5 h-5 w-5 animate-spin text-amber-200" />
            )}

            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-200/60">
                Request
              </p>
              <p className="break-all text-sm text-white/80">
                {backendHealthEndpoint}
              </p>
              <p className="text-sm text-indigo-100">{statusMessage}</p>
              {healthState.kind === "success" ? (
                <p className="text-xs text-indigo-200/70">
                  Response status: {healthState.data.status}
                </p>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </FloatingCard>
  );
}
