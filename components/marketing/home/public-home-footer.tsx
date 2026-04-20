import Link from "next/link";
import { Globe, Mail, Share2, Sparkles } from "lucide-react";

const footerColumns = [
  {
    title: "Company",
    links: [
      { label: "About Us", href: "/#how-it-works" },
      { label: "Contact", href: "mailto:contact@papereasy.ai" },
    ],
  },
  {
    title: "Legal",
    links: [
      {
        label: "Privacy Policy",
        href: "mailto:legal@papereasy.ai?subject=Privacy%20Policy",
      },
      {
        label: "Terms & Conditions",
        href: "mailto:legal@papereasy.ai?subject=Terms%20and%20Conditions",
      },
    ],
  },
];

const socialLinks = [
  { label: "Email", href: "mailto:contact@papereasy.ai", icon: Mail },
  { label: "LinkedIn", href: "/#footer", icon: Globe },
  { label: "GitHub", href: "/#footer", icon: Share2 },
  { label: "Twitter", href: "/#footer", icon: Sparkles },
];

export function PublicHomeFooter() {
  return (
    <footer
      id="footer"
      className="border-t border-white/10 bg-black/35 px-4 py-10 backdrop-blur-2xl md:px-6 lg:px-8"
    >
      <div className="mx-auto max-w-7xl space-y-8">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1.1fr)_repeat(2,minmax(0,220px))]">
          <div className="space-y-4">
            <div>
              <p className="text-2xl font-bold tracking-tight text-white">
                PaperEasy
              </p>
              <p className="mt-2 max-w-md text-sm leading-7 text-indigo-200/68">
                Secure, editorial-grade research assistance for generating,
                refining, and formatting academic papers with confidence.
              </p>
            </div>

            <div className="flex items-center gap-3">
              {socialLinks.map((item) => (
                <Link
                  key={item.label}
                  href={item.href}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-white/5 text-indigo-100/82 transition-colors hover:bg-white/10 hover:text-white"
                  aria-label={item.label}
                >
                  <item.icon className="h-4 w-4" />
                </Link>
              ))}
            </div>
          </div>

          {footerColumns.map((column) => (
            <div key={column.title} className="space-y-4">
              <p className="text-sm font-semibold uppercase tracking-[0.24em] text-indigo-200/80">
                {column.title}
              </p>
              <div className="space-y-3">
                {column.links.map((link) => (
                  <Link
                    key={link.label}
                    href={link.href}
                    className="block text-sm text-zinc-300 transition-colors hover:text-white"
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="border-t border-white/10 pt-6 text-sm text-zinc-400">
          &copy; 2026 PaperEasy. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
