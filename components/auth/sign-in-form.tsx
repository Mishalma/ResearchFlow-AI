"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { KeyRound, LockKeyhole, Mail } from "lucide-react";
import { signInWithEmailAndPassword, signInWithPopup } from "firebase/auth";

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
  AuthTextField,
  FirebaseConfigNotice,
  GoogleAuthButton,
  PasswordField,
} from "@/components/auth/auth-ui";

type SignInFormProps = {
  nextPath: string;
};

export function SignInForm({ nextPath }: SignInFormProps) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const firebaseConfigured = isFirebaseClientConfigured();

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

  async function handleEmailAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      const auth = getFirebaseClientAuth();
      await signInWithEmailAndPassword(auth, email.trim(), password);
      await finalizeBrowserSignIn({ nextPath, router });
    } catch (reason) {
      setError(getFirebaseAuthErrorMessage(reason, "signin"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthCardShell
      badge="Secure Access"
      icon={LockKeyhole}
      title="Sign in to PaperEasy"
      description="Securely access your private research workspace, project history, and export pipeline."
      footer={
        <p className="text-center">
          Don&apos;t have an account?{" "}
          <Link
            href={buildAuthHref("/signup", nextPath)}
            className="font-semibold text-indigo-200 transition-colors hover:text-white"
          >
            Create one
          </Link>
        </p>
      }
    >
      <div className="space-y-5">
        {!firebaseConfigured ? <FirebaseConfigNotice /> : null}

        <GoogleAuthButton
          disabled={!firebaseConfigured || isSubmitting}
          isLoading={isSubmitting}
          onClick={handleGoogleSignIn}
        />

        <AuthDivider label="or sign in with email" />

        <form className="space-y-5" onSubmit={handleEmailAuth}>
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
            placeholder="Enter your password"
            autoComplete="current-password"
            minLength={8}
            required
            labelAdornment={
              <Link
                href={buildAuthHref("/reset-password", nextPath)}
                className="text-xs font-medium text-indigo-200/80 transition-colors hover:text-white"
              >
                Forgot password?
              </Link>
            }
          />

          <AuthFeedback error={error} />

          <AuthSubmitButton
            disabled={!firebaseConfigured || isSubmitting}
            isLoading={isSubmitting}
          >
            Sign in
          </AuthSubmitButton>
        </form>
      </div>
    </AuthCardShell>
  );
}
