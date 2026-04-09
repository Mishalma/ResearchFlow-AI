import type { Metadata } from "next";

import "./globals.css";
import { BackgroundParticles } from "@/components/3d/BackgroundParticles";
import { SceneCanvas } from "@/components/3d/SceneCanvas";

export const metadata: Metadata = {
  title: "PaperEasy",
  description: "Secure AI-powered research paper generation workspace.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen overflow-x-hidden bg-background text-foreground antialiased">
        <SceneCanvas className="pointer-events-none fixed inset-0 z-[-1]">
          <BackgroundParticles count={450} />
        </SceneCanvas>
        {children}
      </body>
    </html>
  );
}
