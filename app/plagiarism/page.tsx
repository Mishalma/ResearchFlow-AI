"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ShieldCheck, AlertTriangle, ArrowRight, CornerDownRight } from "lucide-react";
import { Progress } from "@/components/ui/progress";

export default function PlagiarismReportPage() {
  const score = 12;
  const isSafe = score < 15;

  return (
    <div className="max-w-4xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500 pb-10">
      
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight mb-2">Plagiarism Analysis</h1>
          <p className="text-zinc-500">
            Multi-layer verification against academic databases and internal repositories.
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" className="text-zinc-700">Download PDF Report</Button>
          <Button className="bg-[#4F46E5] hover:bg-[#4338CA] text-white">Back to Editor</Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        
        {/* Score Card */}
        <Card className={`col-span-1 border-t-4 ${isSafe ? 'border-t-emerald-500' : 'border-t-red-500'} shadow-sm`}>
          <CardContent className="p-6 text-center">
             <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-zinc-50 border-8 border-zinc-100 mb-4">
               {isSafe ? <ShieldCheck className="w-8 h-8 text-emerald-500" /> : <AlertTriangle className="w-8 h-8 text-red-500" />}
             </div>
             <h2 className="text-5xl font-bold tracking-tighter mb-2">{score}%</h2>
             <p className="text-sm font-semibold text-zinc-900 mb-1">Similarity Index</p>
             <p className="text-xs text-zinc-500">{isSafe ? 'Excellent. Ready for submission.' : 'High overlap detected. Review suggested.'}</p>
             
             <div className="mt-6 space-y-2 text-left bg-zinc-50 p-3 rounded-lg border border-zinc-100">
               <div className="flex justify-between text-xs">
                 <span className="text-zinc-600">Internet Sources</span>
                 <span className="font-semibold">8%</span>
               </div>
               <div className="flex justify-between text-xs">
                 <span className="text-zinc-600">Publications</span>
                 <span className="font-semibold">3%</span>
               </div>
               <div className="flex justify-between text-xs">
                 <span className="text-zinc-600">Student Papers</span>
                 <span className="font-semibold">1%</span>
               </div>
             </div>
          </CardContent>
        </Card>

        {/* Detailed Results */}
        <div className="col-span-1 md:col-span-2 space-y-4">
          <h3 className="font-semibold text-lg">Matched Content</h3>
          
          <Card className="shadow-sm border-zinc-200 overflow-hidden">
            <div className="border-b p-4 bg-zinc-50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 font-bold px-2.5 py-0.5">Match 1</Badge>
                <span className="text-sm font-semibold">Source: IEEE Xplore - 2023 Educational Technology Review</span>
              </div>
              <span className="text-xs font-bold text-red-600 bg-red-100 px-2 py-1 rounded">8% overlap</span>
            </div>
            <CardContent className="p-5">
              <div className="prose prose-zinc max-w-none text-sm leading-relaxed text-zinc-600 bg-white">
                <p>
                  The control group received standard instructional techniques while the experimental group interacted with the <span className="bg-red-100 text-red-900 border-b-2 border-red-300 font-medium">proprietary learning environment. Pre-test and post-test assessments were standardized across both cohorts</span> to ensure validity.
                </p>
              </div>
              
              <div className="mt-4 flex items-start gap-3 p-3 bg-indigo-50 border border-indigo-100 rounded-lg">
                <CornerDownRight className="w-4 h-4 text-indigo-500 mt-0.5" />
                <div className="flex-1">
                  <p className="text-xs font-semibold text-indigo-900 mb-1">AI Rewrite Suggestion</p>
                  <p className="text-sm text-indigo-700 italic">"Standardized assessments were administered to both groups to guarantee validity, comparing traditional methods against the novel learning platform."</p>
                </div>
                <Button size="sm" className="bg-white hover:bg-zinc-50 text-indigo-700 border border-indigo-200 h-8 self-center">
                  Apply Fix
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-sm border-zinc-200 overflow-hidden">
            <div className="border-b p-4 bg-zinc-50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="bg-amber-50 text-amber-700 border-amber-200 font-bold px-2.5 py-0.5">Match 2</Badge>
                <span className="text-sm font-semibold">Source: Internal Repository - Pedagogy Draft</span>
              </div>
              <span className="text-xs font-bold text-amber-600 bg-amber-100 px-2 py-1 rounded">4% overlap</span>
            </div>
            <CardContent className="p-5">
              <div className="prose prose-zinc max-w-none text-sm leading-relaxed text-zinc-600 bg-white">
                <p>
                  <span className="bg-amber-100 text-amber-900 border-b-2 border-amber-300 font-medium">Data gathered from 240 subjects across multiple high-school districts</span> highlighted a significant performance increase when adaptive algorithms were utilized.
                </p>
              </div>
              <div className="mt-4">
                <Button variant="outline" size="sm" className="text-xs h-8">
                  Cite as Self-Reference
                </Button>
              </div>
            </CardContent>
          </Card>

        </div>
      </div>
    </div>
  );
}
