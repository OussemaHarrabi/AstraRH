import type { Metadata } from "next";
import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/source-sans-3";
import "./globals.css";

export const metadata: Metadata = {
  title: "AstraRH",
  description: "AI does the HR work. People decide about people.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
