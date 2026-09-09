import type { Metadata } from "next";
import { Geist, Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";

// Body copy default (replaces Geist as the default body font).
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

// Headings only, applied via the `font-heading` utility.
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

// Small technical labels (badges, timestamps, citation refs), applied via
// the `font-mono` utility.
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Docent — Chat with your documents",
  description:
    "Upload PDFs and ask questions in plain English. Docent retrieves the exact passages behind every answer and cites the source document and page number, so you never have to take an LLM's word for it.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${geistSans.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=block"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        {children}
        <Toaster richColors closeButton position="top-right" />
      </body>
    </html>
  );
}
