"use client";

import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CheckCircle2, FileText, Search, LayoutTemplate } from "lucide-react";
import { Input } from "@/components/ui/input";

const templates = [
  {
    id: "ieee",
    name: "IEEE Transactions",
    description: "Standard IEEE two-column format for engineering and computer science journals.",
    tags: ["Engineering", "Computer Science", "2-Column"],
    popular: true,
  },
  {
    id: "springer",
    name: "Springer LNCS",
    description: "Lecture Notes in Computer Science format. Single column, optimized for readability.",
    tags: ["Computer Science", "Conference", "1-Column"],
    popular: false,
  },
  {
    id: "elsevier",
    name: "Elsevier Article",
    description: "Standard Elsevier journal format for broad scientific publication, including abstract highlighting.",
    tags: ["Science", "Medicine", "Flexible"],
    popular: false,
  },
  {
    id: "nature",
    name: "Nature Publishing",
    description: "Premium single-column format with specific figure placements and extensive references.",
    tags: ["Biology", "Physics", "Premium"],
    popular: true,
  },
  {
    id: "apa7",
    name: "APA 7th Edition",
    description: "Standard American Psychological Association formatting with title page and running head.",
    tags: ["Psychology", "Social Sciences", "Academic"],
    popular: false,
  },
  {
    id: "wiley",
    name: "Wiley Standard",
    description: "Generic Wiley submission template for cross-disciplinary research manuscripts.",
    tags: ["Interdisciplinary", "Journal", "Flexible"],
    popular: false,
  }
];

export default function TemplatesPage() {
  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500 pb-10">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight mb-2">Publishing Templates</h1>
          <p className="text-zinc-500 max-w-xl">
            Choose a target journal or conference format. Our AI will automatically structure your manuscript and references to meet the exact specifications.
          </p>
        </div>
        <div className="relative w-full md:w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
          <Input 
            placeholder="Search templates..." 
            className="pl-9 bg-white border-zinc-200 focus-visible:ring-indigo-500"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {templates.map((template) => (
          <Card key={template.id} className="group hover:border-indigo-300 hover:shadow-md transition-all duration-200 border-zinc-200 bg-white">
            <div className="aspect-[4/3] bg-zinc-50 border-b border-zinc-100 flex items-center justify-center relative overflow-hidden p-6">
              {/* Abstract Template Visual */}
              <div className="w-full h-full bg-white shadow-sm border border-zinc-200 rounded flex flex-col p-4 gap-3 opacity-90 group-hover:scale-105 transition-transform duration-500">
                 {template.id === 'ieee' ? (
                   <div className="flex gap-4 h-full">
                     <div className="flex-1 space-y-2">
                       <div className="h-4 bg-zinc-200 rounded w-3/4 mb-4" />
                       <div className="h-2 bg-zinc-100 rounded w-full" />
                       <div className="h-2 bg-zinc-100 rounded w-full" />
                       <div className="h-2 bg-zinc-100 rounded w-4/5" />
                       <div className="h-10 bg-zinc-100 rounded w-full mt-4" />
                     </div>
                     <div className="flex-1 space-y-2 pt-8">
                       <div className="h-2 bg-zinc-100 rounded w-full" />
                       <div className="h-2 bg-zinc-100 rounded w-full" />
                       <div className="h-2 bg-zinc-100 rounded w-5/6" />
                     </div>
                   </div>
                 ) : (
                   <div className="h-full flex flex-col space-y-3 items-center pt-2">
                     <div className="h-5 bg-zinc-200 rounded w-1/2 text-center" />
                     <div className="h-2 bg-zinc-100 rounded w-1/3" />
                     <div className="w-full space-y-1.5 mt-4">
                       <div className="h-1.5 bg-zinc-100 rounded w-full" />
                       <div className="h-1.5 bg-zinc-100 rounded w-full" />
                       <div className="h-1.5 bg-zinc-100 rounded w-4/5" />
                     </div>
                   </div>
                 )}
              </div>
              
              {template.popular && (
                <Badge className="absolute top-4 right-4 bg-indigo-500 hover:bg-indigo-600 text-white border-transparent">
                  Popular
                </Badge>
              )}
            </div>
            
            <CardContent className="p-5">
              <h3 className="text-lg font-bold text-zinc-900 mb-2">{template.name}</h3>
              <p className="text-sm text-zinc-500 line-clamp-2 h-10 mb-4">
                {template.description}
              </p>
              <div className="flex flex-wrap gap-2">
                {template.tags.map(tag => (
                  <span key={tag} className="text-[10px] font-semibold tracking-wider uppercase bg-zinc-100 text-zinc-600 px-2 py-1 rounded">
                    {tag}
                  </span>
                ))}
              </div>
            </CardContent>
            
            <CardFooter className="p-5 pt-0 flex gap-3">
              <Button variant="outline" className="flex-1 border-zinc-300 text-zinc-700 font-semibold text-xs">
                <FileText className="w-3.5 h-3.5 mr-2" /> Preview
              </Button>
              <Button className="flex-1 bg-zinc-900 hover:bg-zinc-800 text-white font-semibold text-xs">
                <CheckCircle2 className="w-3.5 h-3.5 mr-2" /> Select
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  );
}
