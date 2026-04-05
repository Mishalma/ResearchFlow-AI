"use client";

import { Bell, HelpCircle, Search, Sparkles } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";

export function Header() {
  return (
    <header className="h-16 border-b border-white/10 bg-black/20 backdrop-blur-lg flex items-center justify-between px-6 md:px-8 sticky top-0 z-40 w-full shadow-[0_4px_30px_rgba(0,0,0,0.1)]">
      <div className="w-full max-w-md xl:max-w-xl relative flex items-center hidden md:flex">
        <Search className="absolute left-3 w-4 h-4 text-zinc-400" />
        <Input
          placeholder="Search manuscripts, citations, or data..."
          className="pl-9 bg-white/5 border-white/10 text-white placeholder:text-zinc-500 focus-visible:bg-white/10 focus-visible:ring-1 focus-visible:border-indigo-500/50 focus-visible:ring-indigo-500/50 w-full h-10 rounded-full transition-all"
        />
      </div>

      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" className="text-zinc-400 hover:text-white hover:bg-white/10 rounded-full w-9 h-9 transition-colors">
          <Bell className="w-4 h-4" />
        </Button>
        <Button variant="ghost" size="icon" className="text-zinc-400 hover:text-white hover:bg-white/10 rounded-full w-9 h-9 transition-colors">
          <HelpCircle className="w-4 h-4" />
        </Button>
        <Button variant="ghost" size="icon" className="text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/20 rounded-full w-9 h-9 transition-all drop-shadow-[0_0_8px_rgba(79,70,229,0.8)]">
          <Sparkles className="w-4 h-4" />
        </Button>

        <div className="h-6 w-px bg-white/10 mx-2" />

        <div className="flex items-center gap-3 cursor-pointer group">
          <div className="text-right hidden md:block">
            <p className="text-sm font-medium text-white leading-none mb-1 group-hover:text-indigo-300 transition-colors">ResearchFlow Workspace</p>
            <p className="text-xs text-indigo-400/70 leading-none tracking-wide">LIVE BACKEND CONNECTED</p>
          </div>
          <Avatar className="h-9 w-9 border border-indigo-500/30 ring-2 ring-transparent group-hover:ring-indigo-500/50 transition-all shadow-[0_0_15px_rgba(79,70,229,0.3)]">
            <AvatarImage src="/avatar.jpg" alt="ResearchFlow workspace" />
            <AvatarFallback className="bg-indigo-950 text-indigo-200 text-xs font-bold">RF</AvatarFallback>
          </Avatar>
        </div>
      </div>
    </header>
  );
}
