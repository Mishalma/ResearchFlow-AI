"use client";

import { Canvas } from "@react-three/fiber";
import { ReactNode } from "react";

interface SceneCanvasProps {
  children: ReactNode;
  className?: string;
  pointerEvents?: "none" | "auto";
}

export function SceneCanvas({ children, className = "", pointerEvents = "none" }: SceneCanvasProps) {
  return (
    <div 
      className={`absolute inset-0 z-0 ${pointerEvents === "none" ? "pointer-events-none" : "pointer-events-auto"} ${className}`}
    >
      <Canvas 
        dpr={[1, 2]} 
        camera={{ position: [0, 0, 5], fov: 45 }}
        gl={{ antialias: true, alpha: true }}
      >
        {children}
      </Canvas>
    </div>
  );
}
