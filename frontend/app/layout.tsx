import type { Metadata } from "next";
import {
  Geist,
  Geist_Mono,
  Noto_Sans_Devanagari,
  Noto_Sans_Malayalam,
  Special_Elite,
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

const display = Special_Elite({
  variable: "--font-display-face",
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
  title: "Chordex — Drop a song, get a playable chord sheet",
  applicationName: "Chordex",
  description:
    "Chords and lyrics with every chord on the exact syllable where it changes. Transpose, Easy Mode, and Hindi / Malayalam lyrics in English letters.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${display.variable} ${mono.variable} ${notoDeva.variable} ${notoMlym.variable} antialiased`}
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
