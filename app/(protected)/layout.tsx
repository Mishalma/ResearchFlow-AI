import { redirect } from "next/navigation";

import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";
import { getServerSessionUser } from "@/lib/server/auth/session";

export const dynamic = "force-dynamic";

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getServerSessionUser();

  if (!user) {
    redirect("/login");
  }

  return (
    <div className="min-h-screen lg:pl-64">
      <Sidebar />
      <div className="flex min-h-screen w-full flex-col">
        <Header user={user} />
        <main className="flex-1 px-4 pb-12 pt-6 md:px-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
