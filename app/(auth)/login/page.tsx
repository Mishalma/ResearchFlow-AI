import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { SignInForm } from "@/components/auth/sign-in-form";
import { AuthPageSearchParams, resolveNextPath } from "@/lib/auth/routing";
import { getServerSessionUser } from "@/lib/server/auth/session";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Sign In | PaperEasy",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: AuthPageSearchParams;
}) {
  const user = await getServerSessionUser();
  const resolvedSearchParams = await searchParams;
  const nextPath = resolveNextPath(resolvedSearchParams.next);

  if (user) {
    redirect(nextPath);
  }

  return <SignInForm nextPath={nextPath} />;
}
