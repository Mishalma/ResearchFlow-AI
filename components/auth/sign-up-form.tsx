"use client";

import { useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  createUserWithEmailAndPassword,
  sendEmailVerification,
  signInWithPopup,
  signOut,
} from "firebase/auth";
import { CheckCheck, KeyRound, LockKeyhole, Mail } from "lucide-react";

import { buildAuthHref } from "@/lib/auth/routing";
import {
  createGoogleProvider,
  getFirebaseClientAuth,
  isFirebaseClientConfigured,
} from "@/lib/firebase/client";
import {
  finalizeBrowserSignIn,
  getFirebaseAuthErrorMessage,
} from "@/components/auth/auth-client";
import {
  AuthCardShell,
  AuthDivider,
  AuthFeedback,
  AuthSubmitButton,
  AuthSuccessPanel,
  AuthTextField,
  FirebaseConfigNotice,
  GoogleAuthButton,
  PasswordField,
} from "@/components/auth/auth-ui";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type SignUpFormProps = {
  nextPath: string;
};

export function SignUpForm({ nextPath }: SignUpFormProps) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdEmail, setCreatedEmail] = useState<string | null>(null);
  const firebaseConfigured = isFirebaseClientConfigured();

  const passwordMismatch =
    confirmPassword.trim().length > 0 && password !== confirmPassword;

  const helperError = useMemo(() => {
    if (passwordMismatch) {
      return "Passwords do not match yet. Confirm the same password to continue.";
    }

    return error;
  }, [error, passwordMismatch]);

  async function handleGoogleSignIn() {
    setIsSubmitting(true);
    setError(null);

    try {
      const auth = getFirebaseClientAuth();
      await signInWithPopup(auth, createGoogleProvider());
      await finalizeBrowserSignIn({ nextPath, router });
    } catch (reason) {
      setError(getFirebaseAuthErrorMessage(reason, "google"));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSignUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match yet. Confirm the same password to continue.");
      setIsSubmitting(false);
      return;
    }

    try {
      const auth = getFirebaseClientAuth();
      const credential = await createUserWithEmailAndPassword(
        auth,
        email.trim(),
        password,
      );
      await sendEmailVerification(credential.user);
      await signOut(auth);
      setCreatedEmail(email.trim());
      setPassword("");
      setConfirmPassword("");
    } catch (reason) {
      setError(getFirebaseAuthErrorMessage(reason, "signup"));
    } finally {
      setIsSubmitting(false);
    }
  }

  const signInHref = buildAuthHref("/login", nextPath);

  return (
    <AuthCardShell
      badge="New Workspace"
      icon={LockKeyhole}
      title="Create your account"
      description="Start a secure PaperEasy workspace for drafting, citation enrichment, and polished exports."
      footer={
        <p className="text-center">
          Already have an account?{" "}
          <Link
            href={signInHref}
            className="font-semibold text-indigo-200 transition-colors hover:text-white"
          >
            Sign in
          </Link>
        </p>
      }
    >
      {createdEmail ? (
        <AuthSuccessPanel
          title="Check your inbox"
          description={`We sent a verification link to ${createdEmail}. Verify your email, then come back to sign in and continue into PaperEasy.`}
          actions={
            <div className="space-y-3">
              <Link
                href={signInHref}
                className={cn(
                  buttonVariants({ size: "lg" }),
                  "flex h-12 w-full rounded-2xl border border-indigo-300/15 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 text-white shadow-[0_0_28px_rgba(59,130,246,0.28)] hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400",
                )}
              >
                Continue to sign in
              </Link>
              <button
                type="button"
                onClick={() => {
                  setCreatedEmail(null);
                  setError(null);
                }}
                className="w-full rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-white/10"
              >
                Use a different email
              </button>
            </div>
          }
        />
      ) : (
        <div className="space-y-5">
          {!firebaseConfigured ? <FirebaseConfigNotice /> : null}

          <GoogleAuthButton
            disabled={!firebaseConfigured || isSubmitting}
            isLoading={isSubmitting}
            onClick={handleGoogleSignIn}
            label="Continue with Google"
          />

          <AuthDivider label="or create with email" />

          <form className="space-y-5" onSubmit={handleSignUp}>
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

            <PasswordField
              label="Password"
              icon={KeyRound}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Create a password"
              autoComplete="new-password"
              minLength={8}
              required
            />

            <PasswordField
              label="Confirm password"
              icon={CheckCheck}
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="Repeat your password"
              autoComplete="new-password"
              minLength={8}
              required
            />

            <AuthFeedback error={helperError} />

            <AuthSubmitButton
              disabled={!firebaseConfigured || isSubmitting}
              isLoading={isSubmitting}
            >
              Create account
            </AuthSubmitButton>
          </form>
        </div>
      )}
    </AuthCardShell>
  );
}
