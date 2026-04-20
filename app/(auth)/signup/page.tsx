import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { SignUpForm } from "@/components/auth/sign-up-form";
import { AuthPageSearchParams, resolveNextPath } from "@/lib/auth/routing";
import { getServerSessionUser } from "@/lib/server/auth/session";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Create Account | PaperEasy",
};

export default async function SignupPage({
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

  return <SignUpForm nextPath={nextPath} />;
}
