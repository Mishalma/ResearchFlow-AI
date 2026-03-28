"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Progress } from "@/components/ui/progress";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FileSearch, Layers, FileEdit, CheckCircle2 } from "lucide-react";
import { SceneCanvas } from "@/components/3d/SceneCanvas";
import { AICore } from "@/components/3d/AICore";

const steps = [
  {
    id: 1,
    title: "Extracting Content",
    description: "Analyzing text, figures, and extracting key citations from the raw document.",
    icon: FileSearch,
  },
  {
    id: 2,
    title: "Structuring Sections",
    description: "Building the narrative arc: Abstract, Introduction, Methodology, and Conclusion.",
    icon: Layers,
  },
  {
    id: 3,
    title: "Formatting to IEEE",
    description: "Applying academic standards, cross-referencing citations, and perfecting the layout.",
    icon: FileEdit,
  },
];

export default function ProcessingPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    // Simulate overall progress and step transitions
    const totalDuration = 8000; // 8 seconds total
    const intervalTime = 100;
    const progressIncrement = 100 / (totalDuration / intervalTime);

    const timer = setInterval(() => {
      setProgress((prev) => {
        const next = prev + progressIncrement;
        
        // Update steps based on progress
        if (next > 33 && next <= 66) setCurrentStep(2);
        if (next > 66 && next <= 100) setCurrentStep(3);
        
        if (next >= 100) {
          clearInterval(timer);
          setTimeout(() => {
            router.push("/editor");
          }, 600);
          return 100;
        }
        return next;
      });
    }, intervalTime);

    return () => clearInterval(timer);
  }, [router]);

  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-8rem)] max-w-2xl mx-auto w-full px-4 relative">
      {/* 3D Core Visual in Background */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-lg h-96 -mt-20 z-0 pointer-events-none opacity-80">
        <SceneCanvas className="w-full h-full">
          <AICore fast={currentStep > 1} />
        </SceneCanvas>
      </div>

      <div className="text-center mb-10 mt-32 relative z-10">
        <h1 className="text-3xl md:text-5xl font-bold tracking-tight mb-3 text-white drop-shadow-[0_0_15px_rgba(79,70,229,0.5)]">
          Synthesizing your Research
        </h1>
        <p className="text-indigo-200/80 text-lg">
          Please wait while our AI engine curates your manuscript.
        </p>
      </div>

      <Card className="w-full p-8 shadow-[0_0_30px_rgba(79,70,229,0.15)] border-white/10 rounded-2xl bg-black/40 backdrop-blur-xl relative overflow-hidden z-10">
        {/* Glow effect */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-3/4 h-32 bg-indigo-500 opacity-10 rounded-[100%] blur-3xl pointer-events-none" />
        {/* Progress Bar */}
        <div className="mb-10 relative">
          <div className="flex justify-between text-sm font-semibold text-indigo-200 mb-3">
            <span>Overall Progress</span>
            <span className="text-indigo-400 drop-shadow-[0_0_5px_rgba(129,140,248,0.8)]">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} className="h-2 bg-white/10 [&>div]:bg-indigo-500 shadow-[0_0_10px_rgba(79,70,229,0.3)]" />
        </div>

        {/* Steps List */}
        <div className="space-y-6 relative">
          <div className="absolute left-6 top-6 bottom-6 w-0.5 bg-white/10 hidden sm:block" />
          
          {steps.map((step, index) => {
            const isActive = currentStep === step.id;
            const isCompleted = currentStep > step.id;
            const isPending = currentStep < step.id;

            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.2 }}
                className={`relative flex items-start gap-5 p-4 rounded-xl transition-all duration-500 ${isActive ? "bg-indigo-500/10 border border-indigo-500/20 shadow-[inset_0_0_20px_rgba(79,70,229,0.1)]" : "border border-transparent"}`}
              >
                <div className={`relative z-10 flex items-center justify-center w-12 h-12 rounded-full shrink-0 border-2 transition-all duration-500
                  ${isCompleted ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-400 drop-shadow-[0_0_10px_rgba(52,211,153,0.5)]" : 
                    isActive ? "bg-indigo-500/20 border-indigo-400 text-indigo-300 shadow-[0_0_15px_rgba(79,70,229,0.5)]" : 
                    "bg-white/5 border-white/10 text-white/30"}
                `}>
                  {isCompleted ? (
                    <CheckCircle2 className="w-6 h-6" />
                  ) : (
                    <step.icon className={`w-5 h-5 ${isActive ? "animate-pulse" : ""}`} />
                  )}
                </div>

                <div className="flex-1 pt-1.5 min-w-0">
                  <div className="flex items-center gap-3 mb-1">
                    <h3 className={`text-lg font-bold transition-colors duration-500 ${isActive ? "text-white" : isCompleted ? "text-indigo-200" : "text-white/40"}`}>
                      {step.title}
                    </h3>
                    {isActive && (
                      <Badge className="bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30 border border-indigo-500/30 font-semibold text-[10px] uppercase tracking-wider px-2 py-0">
                        In Progress
                      </Badge>
                    )}
                  </div>
                  <p className={`text-sm transition-colors duration-500 ${isActive || isCompleted ? "text-indigo-200/70" : "text-white/30"}`}>
                    {step.description}
                  </p>
                </div>
              </motion.div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

