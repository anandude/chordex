import type { Metadata } from "next";
import { Geist, Geist_Mono, Noto_Sans_Devanagari, Noto_Sans_Malayalam } from "next/font/google";
import localFont from "next/font/local";
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

const retroByte = localFont({
  src: "../fonts/RetroByte.ttf",
  variable: "--font-retro-byte",
  weight: "400",
  display: "swap",
});

const claireMono = localFont({
  src: "../fonts/CSClaireMono-Regular.otf",
  variable: "--font-claire",
  weight: "400",
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
  title: "ChordLens — Guitar Chord Analyzer",
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
        className={`${geistSans.variable} ${geistMono.variable} ${retroByte.variable} ${claireMono.variable} ${notoDeva.variable} ${notoMlym.variable} antialiased`}
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
