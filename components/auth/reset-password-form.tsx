"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { KeyRound, Mail } from "lucide-react";
import { sendPasswordResetEmail } from "firebase/auth";

import { buildAuthHref } from "@/lib/auth/routing";
import {
  getFirebaseClientAuth,
  isFirebaseClientConfigured,
} from "@/lib/firebase/client";
import { getFirebaseAuthErrorMessage } from "@/components/auth/auth-client";
import {
  AuthCardShell,
  AuthFeedback,
  AuthSubmitButton,
  AuthSuccessPanel,
  AuthTextField,
  FirebaseConfigNotice,
} from "@/components/auth/auth-ui";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ResetPasswordFormProps = {
  nextPath: string;
};

export function ResetPasswordForm({ nextPath }: ResetPasswordFormProps) {
  const [email, setEmail] = useState("");
  const [sentEmail, setSentEmail] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const firebaseConfigured = isFirebaseClientConfigured();
  const signInHref = buildAuthHref("/login", nextPath);

  async function handleReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      const auth = getFirebaseClientAuth();
      await sendPasswordResetEmail(auth, email.trim());
      setSentEmail(email.trim());
    } catch (reason) {
      setError(getFirebaseAuthErrorMessage(reason, "reset"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthCardShell
      badge="Recovery"
      icon={KeyRound}
      title="Reset your password"
      description="Enter your account email and we&apos;ll send you a secure link to reset your password."
      footer={
        <p className="text-center">
          Remembered it?{" "}
          <Link
            href={signInHref}
            className="font-semibold text-indigo-200 transition-colors hover:text-white"
          >
            Back to sign in
          </Link>
        </p>
      }
    >
      {sentEmail ? (
        <AuthSuccessPanel
          title="Reset link sent"
          description={`A password reset link was sent to ${sentEmail}. Open the email, reset your password, and then come back to sign in.`}
          actions={
            <div className="space-y-3">
              <Link
                href={signInHref}
                className={cn(
                  buttonVariants({ size: "lg" }),
                  "flex h-12 w-full rounded-2xl border border-indigo-300/15 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 text-white shadow-[0_0_28px_rgba(59,130,246,0.28)] hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400",
                )}
              >
                Back to sign in
              </Link>
              <button
                type="button"
                onClick={() => {
                  setSentEmail(null);
                  setError(null);
                }}
                className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-white/10"
              >
                Send another link
              </button>
            </div>
          }
        />
      ) : (
        <div className="space-y-5">
          {!firebaseConfigured ? <FirebaseConfigNotice /> : null}

          <form className="space-y-5" onSubmit={handleReset}>
            <AuthTextField
              label="Email address"
              icon={Mail}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@company.com"
              autoComplete="email"
              required
            />

            <AuthFeedback error={error} />

            <AuthSubmitButton
              disabled={!firebaseConfigured || isSubmitting}
              isLoading={isSubmitting}
            >
              Send reset link
            </AuthSubmitButton>
          </form>
        </div>
      )}
    </AuthCardShell>
  );
}
