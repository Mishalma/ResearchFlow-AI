import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { SceneCanvas } from "@/components/3d/SceneCanvas";
import { BackgroundParticles } from "@/components/3d/BackgroundParticles";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ResearchFlow AI",
  description: "AI-powered Research Paper Generator",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-background min-h-screen text-foreground antialiased overflow-x-hidden`}>
        {/* 3D Global Background */}
        <SceneCanvas className="fixed inset-0 pointer-events-none z-[-1]">
           <BackgroundParticles count={600} />
        </SceneCanvas>

        <Sidebar />
        <div className="lg:pl-64 w-full flex flex-col min-h-screen">
          <Header />
          <main className="flex-1 w-full pt-6 pb-12">
            <div className="max-w-5xl mx-auto px-6 md:px-8 w-full">
              {children}
            </div>
          </main>
        </div>
      </body>
    </html>
  );
}
