"use client";

import { Bell, HelpCircle, Search, Sparkles } from "lucide-react";

import { LogoutButton } from "@/components/auth/logout-button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type HeaderProps = {
  user: {
    name: string;
    email: string;
    imageUrl: string | null;
  };
};

export function Header({ user }: HeaderProps) {
  const initials = user.name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b border-white/10 bg-black/30 px-6 shadow-[0_4px_30px_rgba(0,0,0,0.1)] backdrop-blur-lg md:px-8">
      <div className="relative hidden w-full max-w-md items-center md:flex xl:max-w-xl">
        <Search className="absolute left-3 h-4 w-4 text-zinc-400" />
        <Input
          placeholder="Search papers, figures, or references..."
          className="h-10 w-full rounded-full border-white/10 bg-white/5 pl-9 text-white placeholder:text-zinc-500 focus-visible:border-indigo-500/50 focus-visible:bg-white/10 focus-visible:ring-1 focus-visible:ring-indigo-500/50"
        />
      </div>

      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full text-zinc-400 hover:bg-white/10 hover:text-white">
          <Bell className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full text-zinc-400 hover:bg-white/10 hover:text-white">
          <HelpCircle className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full text-indigo-400 hover:bg-indigo-500/20 hover:text-indigo-300">
          <Sparkles className="h-4 w-4" />
        </Button>
        <div className="mx-1 hidden h-6 w-px bg-white/10 md:block" />
        <div className="hidden items-center gap-3 md:flex">
          <div className="text-right">
            <p className="text-sm font-medium text-white">{user.name}</p>
            <p className="text-xs text-indigo-200/70">{user.email}</p>
          </div>
          <Avatar className="h-9 w-9 border border-indigo-500/30">
            <AvatarImage src={user.imageUrl ?? undefined} alt={user.name} />
            <AvatarFallback className="bg-indigo-950 text-xs font-bold text-indigo-200">
              {initials || "PE"}
            </AvatarFallback>
          </Avatar>
        </div>
        <LogoutButton />
      </div>
    </header>
  );
}
