"use client";

import { useId, useState, type ComponentProps, type ReactNode } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  Loader2,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type AuthCardShellProps = {
  badge: string;
  icon: LucideIcon;
  title: string;
  description: string;
  children: ReactNode;
  footer?: ReactNode;
};

type AuthInputProps = Omit<ComponentProps<typeof Input>, "className"> & {
  label: string;
  icon: LucideIcon;
  className?: string;
  labelAdornment?: ReactNode;
};

type AuthFeedbackProps = {
  message?: string | null;
  error?: string | null;
};

type AuthSuccessPanelProps = {
  title: string;
  description: string;
  actions?: ReactNode;
};

export function AuthCardShell({
  badge,
  icon: Icon,
  title,
  description,
  children,
  footer,
}: AuthCardShellProps) {
  return (
    <section className="relative overflow-hidden rounded-[32px] border border-white/10 bg-[linear-gradient(180deg,rgba(9,12,22,0.82)_0%,rgba(5,7,15,0.94)_100%)] shadow-[0_30px_120px_-60px_rgba(79,70,229,0.85)] backdrop-blur-2xl">
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 h-32 bg-[radial-gradient(circle_at_top,rgba(129,140,248,0.24),transparent_70%)]"
      />
      <div
        aria-hidden
        className="absolute -right-12 top-10 h-44 w-44 rounded-full bg-indigo-500/12 blur-3xl"
      />
      <div
        aria-hidden
        className="absolute -left-10 bottom-0 h-48 w-48 rounded-full bg-sky-400/10 blur-3xl"
      />

      <div className="relative p-6 sm:p-8">
        <div className="mb-8 space-y-4">
          <span className="inline-flex rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.3em] text-indigo-100/76">
            {badge}
          </span>

          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/6 shadow-inner shadow-black/30">
            <Icon className="h-6 w-6 text-indigo-100" />
          </div>

          <div className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-[2rem]">
              {title}
            </h1>
            <p className="max-w-md text-sm leading-7 text-indigo-100/70">
              {description}
            </p>
          </div>
        </div>

        {children}

        {footer ? (
          <div className="mt-8 border-t border-white/8 pt-6 text-sm text-zinc-400">
            {footer}
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function AuthTextField({
  id,
  label,
  icon: Icon,
  className,
  labelAdornment,
  ...props
}: AuthInputProps) {
  const generatedId = useId();
  const controlId = id ?? generatedId;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <label
          htmlFor={controlId}
          className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-100/68"
        >
          {label}
        </label>
        {labelAdornment}
      </div>

      <div className="relative">
        <Icon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <Input
          id={controlId}
          className={cn(
            "h-12 rounded-2xl border-white/10 bg-black/20 pl-11 pr-4 text-white placeholder:text-zinc-500/80 shadow-inner shadow-black/20 focus-visible:border-indigo-300/35 focus-visible:ring-4 focus-visible:ring-indigo-400/12",
            className,
          )}
          {...props}
        />
      </div>
    </div>
  );
}

export function PasswordField({
  id,
  label,
  icon: Icon,
  className,
  labelAdornment,
  ...props
}: AuthInputProps) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  const [visible, setVisible] = useState(false);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <label
          htmlFor={controlId}
          className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-100/68"
        >
          {label}
        </label>
        {labelAdornment}
      </div>

      <div className="relative">
        <Icon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <Input
          id={controlId}
          type={visible ? "text" : "password"}
          className={cn(
            "h-12 rounded-2xl border-white/10 bg-black/20 pl-11 pr-12 text-white placeholder:text-zinc-500/80 shadow-inner shadow-black/20 focus-visible:border-indigo-300/35 focus-visible:ring-4 focus-visible:ring-indigo-400/12",
            className,
          )}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-1 text-zinc-400 transition-colors hover:bg-white/6 hover:text-white"
          aria-label={visible ? "Hide password" : "Show password"}
        >
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}

export function AuthDivider({ label }: { label: string }) {
  return (
    <div className="relative flex items-center gap-4 py-1">
      <div className="h-px flex-1 bg-white/10" />
      <span className="text-[10px] font-semibold uppercase tracking-[0.32em] text-zinc-500">
        {label}
      </span>
      <div className="h-px flex-1 bg-white/10" />
    </div>
  );
}

export function AuthFeedback({ message, error }: AuthFeedbackProps) {
  if (!message && !error) {
    return null;
  }

  return (
    <div aria-live="polite" className="space-y-3">
      {message ? (
        <div
          role="status"
          className="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-50"
        >
          {message}
        </div>
      ) : null}

      {error ? (
        <div
          role="alert"
          className="rounded-2xl border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100"
        >
          {error}
        </div>
      ) : null}
    </div>
  );
}

export function FirebaseConfigNotice() {
  return (
    <div className="rounded-2xl border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-sm leading-6 text-amber-50">
      Firebase Authentication is not configured yet. Add the
      <code className="mx-1 rounded bg-black/20 px-1 py-0.5">
        NEXT_PUBLIC_FIREBASE_*
      </code>
      variables before enabling the hosted auth flow.
    </div>
  );
}

export function GoogleAuthButton({
  disabled,
  isLoading,
  onClick,
  label = "Continue with Google",
}: {
  disabled: boolean;
  isLoading: boolean;
  onClick: () => void | Promise<void>;
  label?: string;
}) {
  return (
    <Button
      type="button"
      onClick={() => void onClick()}
      disabled={disabled}
      className="h-12 w-full rounded-2xl border border-white/10 bg-white/7 text-white hover:bg-white/12"
    >
      {isLoading ? (
        <>
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Connecting...
        </>
      ) : (
        <>
          <GoogleIcon />
          <span>{label}</span>
        </>
      )}
    </Button>
  );
}

export function AuthSubmitButton({
  children,
  disabled,
  isLoading,
}: {
  children: ReactNode;
  disabled: boolean;
  isLoading: boolean;
}) {
  return (
    <Button
      type="submit"
      disabled={disabled}
      className="h-12 w-full rounded-2xl border border-indigo-300/15 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 text-white shadow-[0_0_28px_rgba(59,130,246,0.28)] hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400"
    >
      {isLoading ? (
        <>
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Working...
        </>
      ) : (
        <>
          {children}
          <ArrowRight className="ml-2 h-4 w-4" />
        </>
      )}
    </Button>
  );
}

export function AuthSuccessPanel({
  title,
  description,
  actions,
}: AuthSuccessPanelProps) {
  return (
    <div className="space-y-5">
      <div className="rounded-[28px] border border-emerald-400/20 bg-emerald-500/10 p-5 shadow-[0_24px_80px_-60px_rgba(16,185,129,0.85)]">
        <div className="flex items-start gap-4">
          <div className="mt-0.5 flex h-11 w-11 items-center justify-center rounded-2xl border border-emerald-300/20 bg-emerald-400/10 text-emerald-50">
            <CheckCircle2 className="h-5 w-5" />
          </div>
          <div className="space-y-2">
            <h2 className="text-lg font-semibold tracking-tight text-white">
              {title}
            </h2>
            <p className="text-sm leading-7 text-emerald-50/82">{description}</p>
          </div>
        </div>
      </div>

      {actions}
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg
      className="h-4 w-4"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M12 5.04c1.62 0 3.08.56 4.22 1.66l3.15-3.15C17.45 1.73 14.88 1 12 1 7.22 1 3.22 3.73 1.34 7.72l3.69 2.87C5.9 7.72 8.7 5.04 12 5.04z"
        fill="#EA4335"
      />
      <path
        d="M23.49 12.27c0-.8-.07-1.58-.21-2.33H12v4.4h6.43c-.28 1.48-1.11 2.73-2.37 3.58l3.69 2.87c2.16-1.99 3.74-4.92 3.74-8.52z"
        fill="#4285F4"
      />
      <path
        d="M5.03 14.85c-.24-.71-.38-1.46-.38-2.25s.14-1.54.38-2.25L1.34 7.48C.49 9.17 0 11.04 0 13s.49 3.83 1.34 5.52l3.69-2.67z"
        fill="#FBBC05"
      />
      <path
        d="M12 23c2.97 0 5.46-1 7.28-2.71l-3.69-2.87c-1 .67-2.28 1.07-3.59 1.07-3.3 0-6.1-2.68-7.07-5.55l-3.69 2.87C3.22 20.27 7.22 23 12 23z"
        fill="#34A853"
      />
    </svg>
  );
}
