"use client";

import { motion } from "framer-motion";
import { ReactNode } from "react";

interface FloatingCardProps {
  children: ReactNode;
  className?: string;
  delay?: number;
}

export function FloatingCard({ children, className = "", delay = 0 }: FloatingCardProps) {
  // Using Framer Motion 3D transforms for UI elements instead of full WebGL, 
  // which is much better for accessibility and performance for HTML content.
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.5 }}
      whileHover={{ 
        scale: 1.02, 
        rotateX: 2, 
        rotateY: -2,
        boxShadow: "0 20px 40px -15px rgba(56, 189, 248, 0.15)"
      }}
      className={`relative transform-gpu perspective-1000 ${className}`}
    >
      {/* Glassmorphism background with glow effect */}
      <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/5 to-purple-500/5 rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
      <div className="absolute -inset-0.5 bg-gradient-to-br from-indigo-500/20 to-purple-500/20 rounded-2xl blur opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
      
      <div className="relative h-full w-full bg-black/40 backdrop-blur-xl border border-white/10 rounded-2xl overflow-hidden shadow-2xl">
        {children}
      </div>
    </motion.div>
  );
}
