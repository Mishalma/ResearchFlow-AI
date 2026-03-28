"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { 
  CloudRain, 
  CloudLightning, 
  Cloud, 
  Settings2, 
  Search, 
  MessageSquare,
  ChevronRight,
  ChevronDown,
  LayoutGrid,
  Image as ImageIcon,
  Table,
  MoreVertical,
  CheckCircle2,
  RefreshCcw,
  Sparkles,
  Download,
  Plus
} from "lucide-react";
import { FloatingCard } from "@/components/3d/FloatingCard";

const sections = [
  { id: "abstract", title: "Abstract", status: "completed" },
  { id: "intro", title: "1. Introduction", status: "completed" },
  { id: "lit-review", title: "2. Literature Review", status: "completed" },
  { id: "methodology", title: "3. Methodology", status: "in-progress" },
  { id: "results", title: "4. Results Analysis", status: "pending" },
  { id: "conclusion", title: "5. Conclusion", status: "pending" },
  { id: "references", title: "References", status: "pending" },
];

export default function EditorPage() {
  const [activeSection, setActiveSection] = useState("methodology");
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState<Date>(new Date());

  // Simulate auto-save
  useEffect(() => {
    const timer = setInterval(() => {
      setIsSaving(true);
      setTimeout(() => {
        setIsSaving(false);
        setLastSaved(new Date());
      }, 1000);
    }, 15000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col -mx-4 md:-mx-8 animate-in fade-in duration-500">
      
      {/* Editor Toolbar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/10 bg-black/20 backdrop-blur-lg mt-0">
        <div className="flex items-center gap-4">
          <h1 className="font-bold text-lg text-white tracking-tight drop-shadow-[0_0_8px_rgba(255,255,255,0.3)]">Impact of AI on Modern Pedagogy</h1>
          <Badge variant="outline" className="text-xs font-normal border-white/10 text-indigo-200 bg-white/5">
            {isSaving ? (
              <span className="flex items-center gap-1.5"><RefreshCcw className="w-3 h-3 animate-spin"/> Saving...</span>
            ) : (
              <span className="flex items-center gap-1.5"><Cloud className="w-3 h-3"/> Saved {lastSaved.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
            )}
          </Badge>
        </div>
        
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" className="hidden md:flex text-zinc-400 hover:text-white hover:bg-white/10">
             <MessageSquare className="w-4 h-4 mr-2" /> Comments (3)
          </Button>
          <Button variant="outline" size="sm" className="hidden md:flex border-white/10 text-zinc-300 hover:text-white hover:bg-white/10 bg-transparent">
            <Settings2 className="w-4 h-4 mr-2" /> Settings
          </Button>
          <Button size="sm" className="bg-indigo-600/80 hover:bg-indigo-500 text-white shadow-[0_0_15px_rgba(79,70,229,0.5)] border border-indigo-400/30">
            <Download className="w-4 h-4 mr-2" /> Export
          </Button>
        </div>
      </div>

      {/* Main Split Interface */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* Left Panel: Editor Area */}
        <div className="flex-1 overflow-y-auto bg-transparent relative pb-32">
          
          {/* Mock Floating Formatting Bar */}
          <div className="sticky top-6 z-10 mx-auto w-max bg-black/50 backdrop-blur-xl border border-white/10 shadow-[0_8px_30px_rgba(0,0,0,0.5)] rounded-lg px-2 py-1.5 flex items-center gap-1 text-zinc-300">
            <select className="text-sm font-medium bg-transparent outline-none pl-2 pr-4 py-1 hover:bg-white/10 rounded cursor-pointer text-white">
              <option className="bg-zinc-900">Heading 2</option>
              <option className="bg-zinc-900">Heading 1</option>
              <option className="bg-zinc-900">Normal Text</option>
            </select>
            <div className="w-px h-5 bg-white/10 mx-1" />
            <button className="p-1.5 hover:bg-white/10 rounded font-bold w-8 flex justify-center text-white">B</button>
            <button className="p-1.5 hover:bg-white/10 rounded italic w-8 flex justify-center font-serif text-white">I</button>
            <button className="p-1.5 hover:bg-white/10 rounded underline w-8 flex justify-center text-white">U</button>
            <div className="w-px h-5 bg-white/10 mx-1" />
            <button className="p-1.5 hover:bg-indigo-500/20 text-indigo-300 hover:text-indigo-200 rounded flex gap-1 items-center text-xs font-semibold px-2 transition-colors">
              <Sparkles className="w-3.5 h-3.5" /> AI Rewrite
            </button>
          </div>

          {/* Document Content */}
          <div className="max-w-[800px] mx-auto bg-black/40 backdrop-blur-xl border border-white/10 shadow-[0_0_40px_rgba(0,0,0,0.3)] rounded-xl my-8 p-12 md:p-16 min-h-[1056px] relative overflow-hidden">
            {/* Subtle glow effect behind document */}
            <div className="absolute top-0 right-0 w-96 h-96 bg-indigo-500/5 rounded-full blur-[100px] pointer-events-none" />

            {/* Outline placeholder */}
            <div className="prose prose-invert prose-indigo max-w-none font-serif text-[1.05rem] leading-relaxed text-zinc-300">
              
              <h2 className="text-3xl font-sans font-bold text-white mb-6 tracking-tight drop-shadow-[0_0_8px_rgba(255,255,255,0.2)]">3. Methodology</h2>
              
              <p className="mb-4">
                The methodology section will detail the mixed-methods approach utilized to evaluate the efficacy of AI-driven pedagogical tools in secondary education. A sequential explanatory design was adopted, comprising quantitative student performance data gathering followed by qualitative educator interviews.
              </p>

              <h3 className="text-xl font-sans font-bold text-white mt-8 mb-4 tracking-tight drop-shadow-[0_0_8px_rgba(255,255,255,0.2)]">3.1 Research Design</h3>
              
              <p className="mb-4 text-zinc-400 italic relative group">
                {/* Simulated inline editable area */}
                <span className="absolute -left-6 top-1 text-indigo-400 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer drop-shadow-[0_0_5px_rgba(129,140,248,0.8)]">
                  <Sparkles className="w-4 h-4" />
                </span>
                The study was conducted over a 16-week semester, involving 240 students across three diverse socioeconomic school districts...
              </p>

              <p className="mb-4">
                To isolate the variable of AI intervention, students were divided into a control group receiving traditional instruction techniques and an experimental group utilizing the proprietary ResearchFlow learning environment. Pre-test and post-test assessments were standardized across both cohorts.
              </p>

              <FloatingCard delay={0.1} className="my-8">
                <div className="p-8 bg-black/20 border border-white/5 rounded-lg flex flex-col items-center justify-center text-zinc-400 border-dashed hover:border-indigo-500/30 hover:bg-indigo-500/5 transition-all">
                  <Table className="w-8 h-8 mb-3 text-indigo-400/50" />
                  <span className="text-sm font-sans font-medium text-indigo-200">Drag and drop Table 1 here</span>
                </div>
              </FloatingCard>

              <h3 className="text-xl font-sans font-bold text-white mt-8 mb-4 tracking-tight drop-shadow-[0_0_8px_rgba(255,255,255,0.2)]">3.2 Data Collection and Attrition</h3>
              
              <p className="mb-4">
                Participation required informed consent from guardians resulting in a baseline cohort of 240. However, standard attrition rates were observed, leading to a final sample size (N=221) consisting of 115 in the control group and 106 in the experimental group.
              </p>

            </div>
          </div>
        </div>

        {/* Right Panel: Side Navigation & Tools */}
        <div className="w-80 border-l border-white/10 bg-black/40 backdrop-blur-xl flex flex-col hidden xl:flex shadow-[-10px_0_30px_rgba(0,0,0,0.5)]">
          <Tabs defaultValue="outline" className="w-full flex-1 flex flex-col">
            <div className="px-4 pt-4 pb-2 border-b border-white/10">
              <TabsList className="w-full grid grid-cols-2 bg-white/5 border border-white/10">
                <TabsTrigger value="outline" className="text-xs font-semibold data-[state=active]:bg-indigo-600/80 data-[state=active]:text-white text-zinc-400">Outline</TabsTrigger>
                <TabsTrigger value="assets" className="text-xs font-semibold data-[state=active]:bg-indigo-600/80 data-[state=active]:text-white text-zinc-400">Assets</TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="outline" className="flex-1 m-0 p-0 overflow-y-auto">
              <ScrollArea className="h-full">
                <div className="p-4 space-y-1">
                  <h4 className="text-xs font-bold text-zinc-500 uppercase tracking-wider mb-3 px-2">Document Structure</h4>
                  
                  {sections.map((section) => (
                    <button
                      key={section.id}
                      onClick={() => setActiveSection(section.id)}
                      className={`w-full flex items-center justify-between px-3 py-2 rounded-md text-sm transition-all text-left
                        ${activeSection === section.id 
                          ? "bg-indigo-500/20 text-indigo-200 font-semibold shadow-[inset_0_1px_0_0_rgba(255,255,255,0.1)] ring-1 ring-indigo-500/50" 
                          : "text-zinc-400 hover:text-white hover:bg-white/5 font-medium"}
                      `}
                    >
                      <span>{section.title}</span>
                      
                      {section.status === "completed" && <CheckCircle2 className="w-4 h-4 text-emerald-400 drop-shadow-[0_0_5px_rgba(52,211,153,0.5)]" />}
                      {section.status === "in-progress" && <div className="w-2 h-2 rounded-full bg-amber-400 shadow-[0_0_5px_rgba(251,191,36,0.8)]" />}
                    </button>
                  ))}
                  
                  <div className="pt-4 mt-6 border-t border-white/10 px-2">
                    <Button variant="ghost" className="w-full justify-start text-xs font-semibold text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/20 p-2 h-auto transition-colors">
                      <Sparkles className="w-3.5 h-3.5 mr-2" /> Auto-generate Conclusion
                    </Button>
                  </div>
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="assets" className="flex-1 m-0 p-0 overflow-y-auto">
               <div className="p-4 space-y-6">
                 
                 <div>
                   <div className="flex items-center justify-between mb-3 px-1">
                     <h4 className="text-xs font-bold text-zinc-500 uppercase tracking-wider">Figures</h4>
                     <button className="text-indigo-400 hover:text-indigo-300"><Plus className="w-4 h-4" /></button>
                   </div>
                   
                   <div className="space-y-4 pt-2">
                     <FloatingCard delay={0.1}>
                       <Card className="p-2 border-transparent bg-transparent shadow-none cursor-grab">
                         <div className="aspect-video bg-black/40 backdrop-blur-sm rounded mb-2 flex flex-col items-center justify-center text-zinc-500 border border-white/10 shadow-[inset_0_0_15px_rgba(0,0,0,0.5)]">
                           <ImageIcon className="w-6 h-6 mb-1 opacity-50 text-indigo-200" />
                           <span className="text-[10px] font-medium tracking-wide text-indigo-200">Fig 1. Model</span>
                         </div>
                         <p className="text-[11px] text-zinc-400 line-clamp-2 px-1">
                           Fig 1. Conceptual framework of the AI pedagogy integration.
                         </p>
                       </Card>
                     </FloatingCard>
                   </div>
                 </div>

                 <div>
                   <div className="flex items-center justify-between mb-3 px-1">
                     <h4 className="text-xs font-bold text-zinc-500 uppercase tracking-wider">Tables</h4>
                     <button className="text-indigo-400 hover:text-indigo-300"><Plus className="w-4 h-4" /></button>
                   </div>
                   
                   <div className="space-y-4 pt-2">
                     <FloatingCard delay={0.2}>
                       <Card className="p-2 border-transparent bg-transparent shadow-none cursor-grab">
                         <div className="bg-black/40 backdrop-blur-sm rounded p-3 mb-2 flex items-center justify-center border border-white/10 border-dashed">
                           <Table className="w-5 h-5 text-indigo-400/50" />
                         </div>
                         <p className="text-[11px] text-zinc-400 px-1 font-medium">Table 1. Demographics</p>
                       </Card>
                     </FloatingCard>
                   </div>
                 </div>

               </div>
            </TabsContent>
          </Tabs>
        </div>

      </div>
    </div>
  );
}
