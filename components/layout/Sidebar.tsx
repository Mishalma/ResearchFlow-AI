"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  FileText,
  FolderPlus,
  LayoutTemplate,
  ShieldAlert,
  Settings,
  Plus,
  HelpCircle,
  BookOpen
} from "lucide-react";
import { Button } from "@/components/ui/button";

const navItems = [
  { name: "My Papers", href: "/", icon: FileText },
  { name: "New Project", href: "/new", icon: FolderPlus },
  { name: "Templates", href: "/templates", icon: LayoutTemplate },
  { name: "Plagiarism Reports", href: "/plagiarism", icon: ShieldAlert },
  { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 border-r border-white/10 bg-black/40 backdrop-blur-xl flex-col h-screen fixed top-0 left-0 hidden lg:flex z-50 shadow-[4px_0_24px_-4px_rgba(0,0,0,0.5)]">
      <div className="p-6 pb-4">
        <h1 className="text-xl font-bold tracking-tight text-white drop-shadow-[0_0_8px_rgba(79,70,229,0.5)]">ResearchFlow AI</h1>
        <p className="text-xs text-indigo-300 italic mt-1 font-medium">Academic Curator</p>
      </div>

      <nav className="flex-1 px-4 space-y-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link key={item.name} href={item.href}>
              <span
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-300 cursor-pointer",
                  isActive
                    ? "bg-indigo-500/20 text-indigo-200 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.1)] ring-1 ring-indigo-500/50 drop-shadow-[0_0_10px_rgba(79,70,229,0.3)]"
                    : "text-zinc-400 hover:text-white hover:bg-white/5"
                )}
              >
                <item.icon className={cn("w-4 h-4 transition-colors", isActive ? "text-indigo-400" : "text-zinc-500 group-hover:text-zinc-300")} />
                {item.name}
              </span>
            </Link>
          );
        })}
      </nav>

      <div className="p-5 mt-auto space-y-4">
        <Button className="w-full bg-indigo-600/80 hover:bg-indigo-500 text-white flex justify-start gap-2 shadow-[0_0_15px_rgba(79,70,229,0.5)] border border-indigo-400/30 rounded-lg py-5 backdrop-blur-sm transition-all hover:scale-105 active:scale-95">
          <Plus className="w-4 h-4" />
          New Manuscript
        </Button>
        <div className="space-y-1">
          <Link href="/support" className="flex items-center gap-2 px-3 py-2 text-xs font-medium text-zinc-400 hover:text-white rounded-md hover:bg-white/5 transition-colors">
            <HelpCircle className="w-3.5 h-3.5" /> Support
          </Link>
          <Link href="/docs" className="flex items-center gap-2 px-3 py-2 text-xs font-medium text-zinc-400 hover:text-white rounded-md hover:bg-white/5 transition-colors">
            <BookOpen className="w-3.5 h-3.5" /> Documentation
          </Link>
        </div>
      </div>
    </aside>
  );
}
