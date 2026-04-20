import type { Metadata } from "next";

import { ResetPasswordForm } from "@/components/auth/reset-password-form";
import { AuthPageSearchParams, resolveNextPath } from "@/lib/auth/routing";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Reset Password | PaperEasy",
};

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: AuthPageSearchParams;
}) {
  const resolvedSearchParams = await searchParams;
  const nextPath = resolveNextPath(resolvedSearchParams.next);

  return <ResetPasswordForm nextPath={nextPath} />;
}
