"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";

import { getBrowserCsrfToken } from "@/lib/auth/browser";
import { Button } from "@/components/ui/button";

export function LogoutButton() {
  const router = useRouter();

  async function handleLogout() {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "x-csrf-token": getBrowserCsrfToken(),
      },
    });

    router.push("/login");
    router.refresh();
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={() => void handleLogout()}
      className="border border-white/10 bg-white/5 text-white hover:bg-white/10"
    >
      <LogOut className="mr-2 h-4 w-4" />
      Log Out
    </Button>
  );
}
