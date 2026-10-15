import type { Metadata } from "next";
import {
  Geist,
  Geist_Mono,
  Noto_Sans_Devanagari,
  Noto_Sans_Malayalam,
  Jersey_10,
  Space_Mono,
} from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Open-licensed (SIL OFL) Google Fonts — the repo ships no font files.
const pixel = Jersey_10({
  variable: "--font-pixel-face",
  subsets: ["latin"],
  weight: ["400"],
  display: "swap",
});

const mono = Space_Mono({
  variable: "--font-mono-face",
  subsets: ["latin"],
  weight: ["400"],
  display: "swap",
});

const notoDeva = Noto_Sans_Devanagari({
  variable: "--font-noto-deva",
  subsets: ["devanagari"],
  weight: ["400", "600"],
  display: "swap",
});

const notoMlym = Noto_Sans_Malayalam({
  variable: "--font-noto-mlym",
  subsets: ["malayalam"],
  weight: ["400", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Chordex — chords + lyrics from any song",
  description:
    "Upload a song and get every chord with timestamps, synced lyrics, transpose and easy-chord modes.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${pixel.variable} ${mono.variable} ${notoDeva.variable} ${notoMlym.variable} antialiased`}
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
