"use client";

import { useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  createUserWithEmailAndPassword,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
} from "firebase/auth";
import { ArrowRight, Loader2, LockKeyhole, Mail, UserRound } from "lucide-react";

import { getBrowserCsrfToken } from "@/lib/auth/browser";
import {
  createGoogleProvider,
  getFirebaseClientAuth,
  isFirebaseClientConfigured,
} from "@/lib/firebase/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const defaultRedirectPath = "/new";

type Mode = "signin" | "signup" | "reset";

async function exchangeSession(idToken: string) {
  const csrfToken = getBrowserCsrfToken();
  const response = await fetch("/api/auth/session", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "x-csrf-token": csrfToken,
    },
    body: JSON.stringify({ idToken }),
  });

  if (!response.ok) {
    let message = "Unable to create the authenticated session.";
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload.error) {
        message = payload.error;
      }
    } catch {
      // Ignore parsing errors.
    }

    throw new Error(message);
  }
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<Mode>("signin");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const nextPath = useMemo(() => {
    const next = searchParams.get("next")?.trim();
    return next && next.startsWith("/") ? next : defaultRedirectPath;
  }, [searchParams]);

  const firebaseConfigured = isFirebaseClientConfigured();

  async function completeSignIn() {
    setMessage(null);
    setError(null);
    const auth = getFirebaseClientAuth();
    const user = auth.currentUser;

    if (!user) {
      throw new Error("Firebase sign-in did not return a user.");
    }

    const idToken = await user.getIdToken(true);
    await exchangeSession(idToken);
    await signOut(auth);
    router.push(nextPath);
    router.refresh();
  }

  async function handleGoogleSignIn() {
    setIsSubmitting(true);
    setMessage(null);
    setError(null);

    try {
      const auth = getFirebaseClientAuth();
      await signInWithPopup(auth, createGoogleProvider());
      await completeSignIn();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to sign in with Google.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleEmailAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setMessage(null);
    setError(null);

    try {
      const auth = getFirebaseClientAuth();

      if (mode === "reset") {
        await sendPasswordResetEmail(auth, email.trim());
        setMessage("Password reset email sent. Check your inbox.");
        return;
      }

      if (mode === "signup") {
        const credential = await createUserWithEmailAndPassword(
          auth,
          email.trim(),
          password,
        );
        if (fullName.trim()) {
          await credential.user.reload();
        }
        await sendEmailVerification(credential.user);
        await signOut(auth);
        setMessage(
          "Account created. Verify your email address, then sign in to continue.",
        );
        setMode("signin");
        setPassword("");
        return;
      }

      await signInWithEmailAndPassword(auth, email.trim(), password);
      await completeSignIn();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Authentication failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="border-white/10 bg-black/40 p-8 shadow-[0_0_40px_rgba(0,0,0,0.25)] backdrop-blur-xl">
      <div className="mb-8 space-y-3 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-indigo-400/30 bg-indigo-500/15 text-indigo-200">
          <LockKeyhole className="h-5 w-5" />
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Sign in to PaperEasy</h1>
        <p className="text-sm text-indigo-200/70">
          Securely access your private research projects, generation pipeline, and exports.
        </p>
      </div>

      {!firebaseConfigured ? (
        <div className="rounded-2xl border border-amber-400/20 bg-amber-500/10 p-4 text-sm text-amber-100">
          Firebase Authentication is not configured yet. Add the
          <code className="mx-1 rounded bg-black/20 px-1 py-0.5">NEXT_PUBLIC_FIREBASE_*</code>
          variables before using the hosted login flow.
        </div>
      ) : null}

      <div className="mb-6 grid grid-cols-3 gap-2 rounded-2xl border border-white/10 bg-white/5 p-1">
        {([
          ["signin", "Sign In"],
          ["signup", "Sign Up"],
          ["reset", "Reset"],
        ] as const).map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => {
              setMode(value);
              setMessage(null);
              setError(null);
            }}
            className={`rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
              mode === value
                ? "bg-indigo-600 text-white"
                : "text-zinc-300 hover:bg-white/10 hover:text-white"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="space-y-4">
        <Button
          type="button"
          onClick={() => void handleGoogleSignIn()}
          disabled={!firebaseConfigured || isSubmitting}
          className="w-full border border-white/10 bg-white/10 text-white hover:bg-white/20"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Connecting...
            </>
          ) : (
            <>
              Continue with Google
              <ArrowRight className="ml-2 h-4 w-4" />
            </>
          )}
        </Button>

        <div className="relative py-2 text-center text-xs uppercase tracking-[0.25em] text-zinc-500">
          <span className="relative z-10 bg-black/40 px-3">or with email</span>
          <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-white/10" />
        </div>

        <form className="space-y-4" onSubmit={handleEmailAuth}>
          {mode === "signup" ? (
            <div className="space-y-2">
              <label className="text-sm font-medium text-zinc-200">Full Name</label>
              <div className="relative">
                <UserRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
                <Input
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  placeholder="Your name"
                  className="border-white/10 bg-white/5 pl-9 text-white placeholder:text-zinc-500"
                />
              </div>
            </div>
          ) : null}

          <div className="space-y-2">
            <label className="text-sm font-medium text-zinc-200">Email</label>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
              <Input
                value={email}
                type="email"
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                className="border-white/10 bg-white/5 pl-9 text-white placeholder:text-zinc-500"
                required
              />
            </div>
          </div>

          {mode !== "reset" ? (
            <div className="space-y-2">
              <label className="text-sm font-medium text-zinc-200">Password</label>
              <Input
                value={password}
                type="password"
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter your password"
                className="border-white/10 bg-white/5 text-white placeholder:text-zinc-500"
                minLength={8}
                required
              />
            </div>
          ) : null}

          {message ? (
            <div className="rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
              {message}
            </div>
          ) : null}

          {error ? (
            <div className="rounded-xl border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
              {error}
            </div>
          ) : null}

          <Button
            type="submit"
            disabled={!firebaseConfigured || isSubmitting}
            className="w-full bg-indigo-600 text-white hover:bg-indigo-500"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Working...
              </>
            ) : mode === "signin" ? (
              "Sign In"
            ) : mode === "signup" ? (
              "Create Account"
            ) : (
              "Send Reset Link"
            )}
          </Button>
        </form>
      </div>

      <div className="mt-6 text-center text-sm text-zinc-400">
        <Link href="/" className="text-indigo-300 hover:text-indigo-200">
          Return to the homepage
        </Link>
      </div>
    </Card>
  );
}
