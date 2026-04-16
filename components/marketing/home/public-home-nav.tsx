"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ChevronDown,
  FilePlus2,
  LayoutDashboard,
  LogIn,
  LogOut,
  Menu,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import { getBrowserCsrfToken } from "@/lib/auth/browser";
import type { AuthenticatedUser } from "@/lib/server/auth/session";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type PublicHomeNavProps = {
  user: AuthenticatedUser | null;
};

type NavItem = {
  label: string;
  href: string;
};

function getProtectedHref(user: AuthenticatedUser | null, path: string) {
  return user ? path : `/login?next=${encodeURIComponent(path)}`;
}

export function PublicHomeNav({ user }: PublicHomeNavProps) {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [isScrolled, setIsScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => setIsScrolled(window.scrollY > 12);

    handleScroll();
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const closeMenu = () => setIsOpen(false);
    window.addEventListener("resize", closeMenu);
    return () => window.removeEventListener("resize", closeMenu);
  }, []);

  const navItems = useMemo<NavItem[]>(
    () => [
      { label: "Editor", href: getProtectedHref(user, "/editor") },
      { label: "Projects", href: getProtectedHref(user, "/editor") },
      {
        label: "Plagiarism Remover",
        href: getProtectedHref(user, "/plagiarism"),
      },
      { label: "AI Detection Remover", href: "#features" },
      { label: "Refer & Earn", href: "#refer-earn" },
    ],
    [user],
  );

  const pricingHref = "#pricing";
  const initials = (user?.name ?? "PE")
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  async function handleLogout() {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "x-csrf-token": getBrowserCsrfToken(),
      },
    });

    setIsOpen(false);
    router.push("/");
    router.refresh();
  }

  const shellClasses = cn(
    "sticky top-0 z-50 w-full transition-all duration-300",
    isScrolled
      ? "border-b border-white/10 bg-black/50 shadow-[0_18px_60px_-40px_rgba(0,0,0,0.85)] backdrop-blur-2xl"
      : "bg-black/20 backdrop-blur-lg",
  );

  return (
    <header className={shellClasses}>
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 py-3 md:px-6 lg:px-8">
        <div className="flex items-center gap-10">
          <Link
            href="/"
            className="text-xl font-bold tracking-tight text-white drop-shadow-[0_0_10px_rgba(79,70,229,0.45)]"
          >
            PaperEasy
          </Link>

          <nav className="hidden items-center gap-1 lg:flex">
            {navItems.map((item) => (
              <Link
                key={item.label}
                href={item.href}
                className="rounded-full px-3 py-2 text-sm font-medium text-indigo-100/78 transition-colors hover:bg-white/8 hover:text-white"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="hidden items-center gap-3 lg:flex">
          <Link
            href={pricingHref}
            className="rounded-full px-3 py-2 text-sm font-medium text-indigo-100/78 transition-colors hover:bg-white/8 hover:text-white"
          >
            Pricing
          </Link>

          {user ? (
            <DropdownMenu>
              <DropdownMenuTrigger className="outline-none">
                <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-2 py-1.5 text-sm text-white transition-colors hover:bg-white/10">
                  <Avatar className="h-8 w-8 border border-indigo-400/25">
                    <AvatarImage src={user.imageUrl ?? undefined} alt={user.name} />
                    <AvatarFallback className="bg-indigo-950 text-xs font-bold text-indigo-100">
                      {initials}
                    </AvatarFallback>
                  </Avatar>
                  <ChevronDown className="h-4 w-4 text-zinc-400" />
                </div>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                sideOffset={10}
                className="w-60 rounded-2xl border border-white/10 bg-[#0b1020]/95 p-2 text-white shadow-[0_20px_60px_-30px_rgba(79,70,229,0.6)] backdrop-blur-2xl"
              >
                <DropdownMenuLabel className="px-3 py-2 text-zinc-300">
                  <p className="text-sm font-semibold text-white">{user.name}</p>
                  <p className="mt-1 text-xs text-indigo-200/68">{user.email}</p>
                </DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-white/8" />
                <DropdownMenuItem
                  className="rounded-xl px-3 py-2 text-zinc-200"
                  onClick={() => router.push("/editor")}
                >
                  <LayoutDashboard className="h-4 w-4 text-indigo-300" />
                  Workspace
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="rounded-xl px-3 py-2 text-zinc-200"
                  onClick={() => router.push("/new")}
                >
                  <FilePlus2 className="h-4 w-4 text-indigo-300" />
                  New Project
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="rounded-xl px-3 py-2 text-zinc-200"
                  onClick={() => router.push("/plagiarism")}
                >
                  <ShieldAlert className="h-4 w-4 text-indigo-300" />
                  Plagiarism Remover
                </DropdownMenuItem>
                <DropdownMenuSeparator className="bg-white/8" />
                <DropdownMenuItem
                  className="rounded-xl px-3 py-2 text-zinc-200"
                  onClick={() => void handleLogout()}
                >
                  <LogOut className="h-4 w-4 text-rose-300" />
                  Logout
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Link
              href="/login"
              className={cn(
                buttonVariants({ size: "lg" }),
                "h-10 rounded-full border border-indigo-400/30 bg-indigo-600/80 px-5 text-white shadow-[0_0_20px_rgba(79,70,229,0.4)] hover:bg-indigo-500",
              )}
            >
              <LogIn className="mr-2 h-4 w-4" />
              Login
            </Link>
          )}
        </div>

        <div className="flex items-center gap-2 lg:hidden">
          {user ? (
            <button
              type="button"
              onClick={() => router.push("/editor")}
              className="rounded-full border border-white/10 bg-white/5 p-1.5"
            >
              <Avatar className="h-8 w-8 border border-indigo-400/25">
                <AvatarImage src={user.imageUrl ?? undefined} alt={user.name} />
                <AvatarFallback className="bg-indigo-950 text-xs font-bold text-indigo-100">
                  {initials}
                </AvatarFallback>
              </Avatar>
            </button>
          ) : (
            <Link
              href="/login"
              className={cn(
                buttonVariants({ size: "sm" }),
                "h-9 rounded-full border border-indigo-400/30 bg-indigo-600/80 px-4 text-white hover:bg-indigo-500",
              )}
            >
              Login
            </Link>
          )}

          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={() => setIsOpen((open) => !open)}
            className="rounded-full border border-white/10 bg-white/5 text-white hover:bg-white/10"
          >
            {isOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      <AnimatePresence initial={false}>
        {isOpen ? (
          <motion.div
            initial={{ opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="border-t border-white/10 bg-black/55 px-4 py-4 backdrop-blur-2xl lg:hidden"
          >
            <div className="mx-auto max-w-7xl space-y-3">
              {navItems.map((item) => (
                <Link
                  key={item.label}
                  href={item.href}
                  onClick={() => setIsOpen(false)}
                  className="flex w-full items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-white/10"
                >
                  <span>{item.label}</span>
                  <Sparkles className="h-4 w-4 text-indigo-300" />
                </Link>
              ))}

              <Link
                href={pricingHref}
                onClick={() => setIsOpen(false)}
                className="flex w-full items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-white/10"
              >
                <span>Pricing</span>
                <Sparkles className="h-4 w-4 text-indigo-300" />
              </Link>

              {user ? (
                <button
                  type="button"
                  onClick={() => void handleLogout()}
                  className="flex w-full items-center justify-between rounded-2xl border border-rose-400/20 bg-rose-500/10 px-4 py-3 text-sm font-medium text-rose-100 transition-colors hover:bg-rose-500/15"
                >
                  <span>Logout</span>
                  <LogOut className="h-4 w-4" />
                </button>
              ) : (
                <Link
                  href="/login"
                  onClick={() => setIsOpen(false)}
                  className={cn(
                    buttonVariants({ size: "lg" }),
                    "flex h-11 w-full rounded-2xl border border-indigo-400/30 bg-indigo-600/80 text-white hover:bg-indigo-500",
                  )}
                >
                  <LogIn className="mr-2 h-4 w-4" />
                  Login
                </Link>
              )}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </header>
  );
}
