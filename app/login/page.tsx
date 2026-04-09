import { redirect } from "next/navigation";

import { LoginForm } from "@/components/auth/login-form";
import { getServerSessionUser } from "@/lib/server/auth/session";

export const dynamic = "force-dynamic";

type LoginPageSearchParams = Promise<{
  next?: string | string[];
}>;

function getSingleSearchParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }

  return value ?? null;
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: LoginPageSearchParams;
}) {
  const user = await getServerSessionUser();
  const resolvedSearchParams = await searchParams;
  const nextPath = getSingleSearchParam(resolvedSearchParams.next) ?? "/new";

  if (user) {
    redirect(nextPath.startsWith("/") ? nextPath : "/new");
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] max-w-xl items-center justify-center px-4 py-10">
      <LoginForm />
    </div>
  );
}
