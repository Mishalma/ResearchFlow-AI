"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FileText,
  FolderPlus,
  LayoutTemplate,
  PenSquare,
  ShieldAlert,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const navItems = [
  { name: "Editor", href: "/editor", icon: PenSquare },
  { name: "New Project", href: "/new", icon: FolderPlus },
  { name: "Templates", href: "/templates", icon: LayoutTemplate },
  { name: "Plagiarism", href: "/plagiarism", icon: ShieldAlert },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 z-50 hidden h-screen w-64 flex-col border-r border-white/10 bg-black/45 shadow-[4px_0_24px_-4px_rgba(0,0,0,0.5)] backdrop-blur-xl lg:flex">
      <div className="p-6 pb-4">
        <Link href="/" className="block">
          <h1 className="text-xl font-bold tracking-tight text-white drop-shadow-[0_0_8px_rgba(79,70,229,0.5)]">
            PaperEasy
          </h1>
          <p className="mt-1 text-xs font-medium italic text-indigo-300">
            Secure Research Workspace
          </p>
        </Link>
      </div>

      <nav className="flex-1 space-y-1 px-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link key={item.name} href={item.href}>
              <span
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-300",
                  isActive
                    ? "bg-indigo-500/20 text-indigo-200 ring-1 ring-indigo-500/50 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.1)]"
                    : "text-zinc-400 hover:bg-white/5 hover:text-white",
                )}
              >
                <item.icon
                  className={cn(
                    "h-4 w-4 transition-colors",
                    isActive ? "text-indigo-400" : "text-zinc-500",
                  )}
                />
                {item.name}
              </span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto p-5">
        <Link href="/new">
          <Button className="w-full justify-start gap-2 rounded-lg border border-indigo-400/30 bg-indigo-600/80 py-5 text-white shadow-[0_0_15px_rgba(79,70,229,0.5)] hover:bg-indigo-500">
            <FileText className="h-4 w-4" />
            New Manuscript
          </Button>
        </Link>
      </div>
    </aside>
  );
}
