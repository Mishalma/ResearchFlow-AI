"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  ChevronDown,
  FilePlus2,
  LayoutDashboard,
  LogOut,
  Menu,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import { buildAuthHref, sanitizeNextPath } from "@/lib/auth/routing";
import { getBrowserCsrfToken } from "@/lib/auth/browser";
import type { AuthenticatedUser } from "@/lib/server/auth/session";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { buttonVariants } from "@/components/ui/button";
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
  variant?: "default" | "auth";
};

type NavItem = {
  label: string;
  href: string;
};

type AuthVariantAction = {
  label: string;
  href: string;
};

function getProtectedHref(user: AuthenticatedUser | null, path: string) {
  return user ? path : `/login?next=${encodeURIComponent(path)}`;
}

function getAuthVariantAction(pathname: string | null, nextPath: string): AuthVariantAction {
  switch (pathname) {
    case "/signup":
      return {
        label: "Sign in",
        href: buildAuthHref("/login", nextPath),
      };
    case "/reset-password":
      return {
        label: "Back to sign in",
        href: buildAuthHref("/login", nextPath),
      };
    default:
      return {
        label: "Create account",
        href: buildAuthHref("/signup", nextPath),
      };
  }
}

function NavDropdown({
  label,
  items,
}: {
  label: string;
  items: NavItem[];
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-1 rounded-full px-3 py-2 text-sm font-medium text-indigo-100/74 outline-none transition-colors hover:bg-white/6 hover:text-white">
        <span>{label}</span>
        <ChevronDown className="h-3.5 w-3.5 text-indigo-200/60" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="center"
        sideOffset={12}
        className="min-w-56 rounded-2xl border border-white/10 bg-[#0c1324]/96 p-2 text-white shadow-[0_20px_70px_-35px_rgba(79,70,229,0.7)] backdrop-blur-2xl"
      >
        {items.map((item) => (
          <DropdownMenuItem
            key={item.label}
            className="rounded-xl px-3 py-2.5 text-sm text-zinc-200"
            render={
              <Link href={item.href} className="flex w-full items-center" />
            }
          >
            {item.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function PublicHomeNav({
  user,
  variant = "default",
}: PublicHomeNavProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [isOpen, setIsOpen] = useState(false);
  const [isScrolled, setIsScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => setIsScrolled(window.scrollY > 10);

    handleScroll();
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const closeMenu = () => setIsOpen(false);
    window.addEventListener("resize", closeMenu);
    return () => window.removeEventListener("resize", closeMenu);
  }, []);

  const nextPath = useMemo(
    () => sanitizeNextPath(searchParams.get("next")),
    [searchParams],
  );

  const authVariantAction = useMemo(
    () => getAuthVariantAction(pathname, nextPath),
    [nextPath, pathname],
  );

  const featureItems = useMemo<NavItem[]>(
    () => [
      { label: "Editor", href: getProtectedHref(user, "/editor") },
      { label: "Projects", href: getProtectedHref(user, "/editor") },
      {
        label: "Plagiarism Remover",
        href: getProtectedHref(user, "/plagiarism"),
      },
      { label: "AI Detection Remover", href: "#features" },
    ],
    [user],
  );

  const resourceItems = useMemo<NavItem[]>(
    () => [
      { label: "How It Works", href: "#how-it-works" },
      { label: "Refer & Earn", href: "#refer-earn" },
      { label: "What Users Say", href: "#testimonials" },
    ],
    [],
  );

  const mobileItems = useMemo<NavItem[]>(
    () => [...featureItems, ...resourceItems],
    [featureItems, resourceItems],
  );

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

  if (variant === "auth") {
    return (
      <header className="sticky top-0 z-50 px-4 pt-4 md:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl">
          <div
            className={cn(
              "rounded-[26px] border border-white/10 px-4 py-3 transition-all duration-300 md:px-5",
              isScrolled
                ? "bg-[#0b1120]/92 shadow-[0_22px_70px_-40px_rgba(0,0,0,0.9)] backdrop-blur-2xl"
                : "bg-[#0d1323]/78 shadow-[0_16px_50px_-38px_rgba(79,70,229,0.55)] backdrop-blur-xl",
            )}
          >
            <div className="flex items-center justify-between gap-4">
              <Link
                href="/"
                className="flex min-w-0 items-center gap-3 text-white"
              >
                <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-xl border border-indigo-400/20 bg-gradient-to-br from-indigo-400/70 via-sky-400/45 to-violet-500/70 shadow-[0_0_20px_rgba(96,165,250,0.32)]">
                  <span className="h-2.5 w-2.5 rounded-full bg-white/85" />
                </span>
                <span className="truncate text-lg font-semibold tracking-tight">
                  PaperEasy
                </span>
              </Link>

              <div className="flex items-center gap-2 md:gap-3">
                <Link
                  href="/"
                  className="hidden rounded-full px-3 py-2 text-sm font-medium text-indigo-100/74 transition-colors hover:bg-white/6 hover:text-white md:inline-flex"
                >
                  Home
                </Link>

                {user ? (
                  <Link
                    href="/editor"
                    className={cn(
                      buttonVariants({ size: "lg" }),
                      "h-11 rounded-2xl border border-sky-300/20 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 px-5 text-white shadow-[0_0_24px_rgba(59,130,246,0.38)] hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400",
                    )}
                  >
                    Workspace
                  </Link>
                ) : (
                  <Link
                    href={authVariantAction.href}
                    className={cn(
                      buttonVariants({ size: "lg" }),
                      "h-11 rounded-2xl border border-sky-300/20 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 px-5 text-white shadow-[0_0_24px_rgba(59,130,246,0.38)] hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400",
                    )}
                  >
                    {authVariantAction.label}
                  </Link>
                )}
              </div>
            </div>
          </div>
        </div>
      </header>
    );
  }

  return (
    <header className="sticky top-0 z-50 px-4 pt-4 md:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <div
          className={cn(
            "rounded-[26px] border border-white/10 px-4 py-3 transition-all duration-300 md:px-5",
            isScrolled
              ? "bg-[#0b1120]/92 shadow-[0_22px_70px_-40px_rgba(0,0,0,0.9)] backdrop-blur-2xl"
              : "bg-[#0d1323]/78 shadow-[0_16px_50px_-38px_rgba(79,70,229,0.55)] backdrop-blur-xl",
          )}
        >
          <div className="flex items-center justify-between gap-4">
            <Link
              href="/"
              className="flex min-w-0 items-center gap-3 text-white"
            >
              <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-xl border border-indigo-400/20 bg-gradient-to-br from-indigo-400/70 via-sky-400/45 to-violet-500/70 shadow-[0_0_20px_rgba(96,165,250,0.32)]">
                <span className="h-2.5 w-2.5 rounded-full bg-white/85" />
              </span>
              <span className="truncate text-lg font-semibold tracking-tight">
                PaperEasy
              </span>
            </Link>

            <nav className="hidden items-center gap-1 lg:flex">
              <NavDropdown label="Features" items={featureItems} />
              <NavDropdown label="Resources" items={resourceItems} />
            </nav>

            <div className="hidden items-center gap-2 lg:flex">
              {user ? (
                <>
                  <Link
                    href="/editor"
                    className="rounded-full px-3 py-2 text-sm font-medium text-indigo-100/78 transition-colors hover:bg-white/6 hover:text-white"
                  >
                    Workspace
                  </Link>

                  <DropdownMenu>
                    <DropdownMenuTrigger className="outline-none">
                      <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-2 py-1.5 text-sm text-white transition-colors hover:bg-white/10">
                        <Avatar className="h-8 w-8 border border-indigo-400/25">
                          <AvatarImage
                            src={user.imageUrl ?? undefined}
                            alt={user.name}
                          />
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
                        <p className="text-sm font-semibold text-white">
                          {user.name}
                        </p>
                        <p className="mt-1 text-xs text-indigo-200/68">
                          {user.email}
                        </p>
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
                </>
              ) : (
                <>
                  <Link
                    href="/login"
                    className="rounded-full px-3 py-2 text-sm font-medium text-indigo-100/78 transition-colors hover:bg-white/6 hover:text-white"
                  >
                    Login
                  </Link>
                  <Link
                    href="/login?next=%2Fnew"
                    className={cn(
                      buttonVariants({ size: "lg" }),
                      "h-11 rounded-2xl border border-sky-300/20 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 px-5 text-white shadow-[0_0_24px_rgba(59,130,246,0.38)] hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400",
                    )}
                  >
                    Get Started
                  </Link>
                </>
              )}
            </div>

            <div className="flex items-center gap-2 lg:hidden">
              {!user ? (
                <Link
                  href="/login?next=%2Fnew"
                  className={cn(
                    buttonVariants({ size: "sm" }),
                    "h-9 rounded-xl border border-sky-300/20 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 px-4 text-white hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400",
                  )}
                >
                  Start
                </Link>
              ) : (
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
              )}

              <button
                type="button"
                onClick={() => setIsOpen((open) => !open)}
                className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-white transition-colors hover:bg-white/10"
              >
                {isOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
              </button>
            </div>
          </div>
        </div>

        <AnimatePresence initial={false}>
          {isOpen ? (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              className="mt-3 rounded-[24px] border border-white/10 bg-[#0b1120]/90 p-4 shadow-[0_20px_60px_-40px_rgba(0,0,0,0.9)] backdrop-blur-2xl lg:hidden"
            >
              <div className="space-y-3">
                {mobileItems.map((item) => (
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
                  <div className="flex gap-3 pt-2">
                    <Link
                      href="/login"
                      onClick={() => setIsOpen(false)}
                      className="flex h-11 flex-1 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-sm font-medium text-white transition-colors hover:bg-white/10"
                    >
                      Login
                    </Link>
                    <Link
                      href="/login?next=%2Fnew"
                      onClick={() => setIsOpen(false)}
                      className={cn(
                        buttonVariants({ size: "lg" }),
                        "flex h-11 flex-1 rounded-2xl border border-sky-300/20 bg-gradient-to-r from-sky-500 via-indigo-500 to-blue-500 text-white hover:from-sky-400 hover:via-indigo-400 hover:to-blue-400",
                      )}
                    >
                      Get Started
                    </Link>
                  </div>
                )}
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </header>
  );
}
