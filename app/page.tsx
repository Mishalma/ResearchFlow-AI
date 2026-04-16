import { getServerSessionUser } from "@/lib/server/auth/session";
import { HeroSection } from "@/components/marketing/home/hero-section";
import { TrustStrip } from "@/components/marketing/home/trust-strip";
import { HowItWorksSection } from "@/components/marketing/home/how-it-works-section";
import { FeaturesSection } from "@/components/marketing/home/features-section";
import { DashboardPreviewSection } from "@/components/marketing/home/dashboard-preview-section";
import { PricingTeaserSection } from "@/components/marketing/home/pricing-teaser-section";
import { TestimonialsSection } from "@/components/marketing/home/testimonials-section";
import { ReferEarnSection } from "@/components/marketing/home/refer-earn-section";
import { PublicHomeFooter } from "@/components/marketing/home/public-home-footer";
import { PublicHomeNav } from "@/components/marketing/home/public-home-nav";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const user = await getServerSessionUser();

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
      <PublicHomeNav user={user} />
      <main className="pb-12">
        <HeroSection user={user} />
        <TrustStrip />
        <HowItWorksSection />
        <FeaturesSection />
        <DashboardPreviewSection />
        <PricingTeaserSection user={user} />
        <TestimonialsSection />
        <ReferEarnSection user={user} />
      </main>
      <PublicHomeFooter />
    </div>
  );
}
