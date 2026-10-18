import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { Music, Sparkles, Languages, Play, Upload, Guitar } from "lucide-react";

export const metadata: Metadata = {
  title: "Chordex — Drop a song, get a playable chord sheet",
  description:
    "Chords and lyrics with every chord on the exact syllable where it changes. Transpose, Easy Mode, and Hindi / Malayalam lyrics in English letters.",
};

const FEATURES = [
  {
    icon: Guitar,
    title: "Chords on the syllable",
    body: "Lyrics are force-aligned to the audio, and every chord change is anchored to the exact word — or syllable — where it lands, like a hand-made chord sheet.",
  },
  {
    icon: Sparkles,
    title: "Any song, any key",
    body: "Upload MP3, WAV, OGG or FLAC, or just paste a YouTube link. Transpose up or down 11 semitones to fit your voice.",
  },
  {
    icon: Music,
    title: "Easy Mode",
    body: "One tap rewrites the whole sheet into a capo position with beginner-friendly open shapes — no barre chords required.",
  },
  {
    icon: Languages,
    title: "Indian languages first",
    body: "Tuned speech models for Hindi and Malayalam. Read the lyrics in the original script or in everyday English letters.",
  },
  {
    icon: Play,
    title: "Play along",
    body: "A chord-coloured scrubber, a live NOW/NEXT chord bar, and the sung line highlighted in real time. Space plays, space pauses.",
  },
  {
    icon: Upload,
    title: "Take it with you",
    body: "Copy the sheet out as ChordPro text — chords inline on their syllables — and paste it into any tool you already use.",
  },
];

const ROMAN_EXAMPLES = [
  { original: "दिल की धड़कन", roman: "dil ki dhadkan" },
  { original: "मैं तुम्हें समझता हूँ", roman: "main tumhein samajhta hun" },
  { original: "നിന്റെ കണ്ണുകളിൽ", roman: "ninte kannukalil" },
  { original: "ഞാൻ കണ്ടു", roman: "njaan kandu" },
];

const STEPS = [
  {
    n: "01",
    title: "Drop it in",
    body: "An audio file or a YouTube link — either works. Add the title and artist to unlock verified lyrics.",
  },
  {
    n: "02",
    title: "The studio listens",
    body: "Chords are detected, the key and tempo are estimated, and vocals are aligned word by word to the audio.",
  },
  {
    n: "03",
    title: "Play along",
    body: "Follow the coloured scrubber and the NOW/NEXT bar as the song plays. Transpose or flip on Easy Mode any time.",
  },
];

const HERO_BG = "https://images.pexels.com/photos/27508913/pexels-photo-27508913.jpeg?auto=compress&cs=tinysrgb&w=1920";

export default function Landing() {
  return (
    <div className="min-h-screen bg-ink text-paper">
      {/* Nav */}
      <header className="absolute top-0 inset-x-0 z-30">
        <nav className="flex items-center justify-between px-6 md:px-10 py-5 max-w-[1480px] mx-auto">
          <Link href="/" className="font-display text-2xl md:text-3xl tracking-wide">
            Chordex
          </Link>
          <div className="hidden md:flex items-center gap-8 font-medium text-paper-dim">
            <a href="#features" className="hover:opacity-55 transition-opacity">Features</a>
            <a href="#languages" className="hover:opacity-55 transition-opacity">Languages</a>
            <a href="#how" className="hover:opacity-55 transition-opacity">How it works</a>
            <a href="#see" className="hover:opacity-55 transition-opacity">See it</a>
          </div>
          <Link
            href="/upload"
            className="font-semibold text-white bg-gold rounded-full px-5 py-2.5 hover:opacity-80 active:scale-95 transition-all"
          >
            Get Started
          </Link>
        </nav>
      </header>

      {/* Hero — full viewport, photo backdrop, fading to page black */}
      <section className="relative min-h-[100svh] flex items-center justify-center overflow-hidden">
        <Image
          src={HERO_BG}
          alt=""
          fill
          priority
          sizes="100vw"
          className="object-cover"
        />
        {/* top white fade for nav legibility, bottom fade into the page */}
        <div className="absolute inset-x-0 top-0 h-[687px] bg-gradient-to-b from-white via-white/60 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 h-64 bg-gradient-to-b from-transparent to-ink" />

        <div
          className="relative w-[calc(100vw-48px)] max-w-2xl rounded-[44px] bg-white/[0.06] border-[3px] border-white backdrop-blur-[20px] shadow-[0_18px_50px_rgba(0,0,0,0.45)] px-7 py-9 md:px-10 md:py-11 text-center"
        >
          <p className="font-display text-3xl md:text-5xl leading-tight text-white drop-shadow-[0_2px_10px_rgba(0,0,0,0.6)]">
            Play any song tonight
          </p>
          <p className="mt-3 text-white/90 font-medium text-base md:text-lg drop-shadow-[0_1px_6px_rgba(0,0,0,0.6)]">
            Paste a YouTube link and get a chord sheet with every chord sitting
            on the exact syllable where it changes.
          </p>
          <form
            action="/upload"
            method="get"
            className="mt-7 flex flex-col sm:flex-row gap-3"
          >
            <input
              type="url"
              name="youtube"
              inputMode="url"
              placeholder="Paste a YouTube link…"
              aria-label="YouTube link"
              className="flex-1 min-w-0 rounded-full bg-white/[0.12] border-[2px] border-white/70 text-white text-sm font-medium px-4 py-2.5 min-h-11 placeholder:text-white/70 focus:outline-none focus:bg-white/20 transition-colors"
            />
            <button
              type="submit"
              className="shrink-0 font-semibold text-white bg-gold rounded-full px-6 min-h-11 hover:opacity-80 active:scale-95 transition-all"
            >
              Get chords
            </button>
          </form>
          <p className="mt-3 text-white/80 text-xs drop-shadow-[0_1px_4px_rgba(0,0,0,0.6)]">
            Free & open source · runs in ~1–3 min · English, Hindi & Malayalam
          </p>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="max-w-[1480px] mx-auto px-6 md:px-10 py-20 md:py-28">
        <p className="font-display text-3xl md:text-4xl">What you get</p>
        <p className="mt-2 text-paper-dim max-w-xl">
          Everything a hand-made chord sheet gives you, generated for your
          exact recording.
        </p>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="rounded-2xl bg-coal border border-white/10 shadow-hard-sm p-6 hover:opacity-85 transition-opacity"
            >
              <f.icon aria-hidden strokeWidth={2} className="w-7 h-7 text-viol" />
              <p className="mt-4 font-semibold text-lg">{f.title}</p>
              <p className="mt-2 text-sm leading-relaxed text-paper-dim">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Languages */}
      <section id="languages" className="max-w-[1480px] mx-auto px-6 md:px-10 pb-20 md:pb-28">
        <p className="font-display text-3xl md:text-4xl">Sing in your language</p>
        <p className="mt-2 text-paper-dim max-w-2xl">
          Hindi and Malayalam lyrics appear in the original script or in the
          English letters people actually type — the same song, however you
          read it best.
        </p>
        <div className="mt-10 grid gap-5 md:grid-cols-2">
          <div className="rounded-2xl bg-paper text-ink shadow-hard p-7 md:p-9">
            <p className="font-cl text-ink/55 text-[11px] uppercase tracking-[0.2em]">
              The sheet writes
            </p>
            <div className="mt-5 space-y-4">
              {ROMAN_EXAMPLES.map((ex) => (
                <div key={ex.original} className="flex items-baseline justify-between gap-4">
                  <span className="text-xl md:text-2xl">{ex.original}</span>
                  <span className="font-cl text-viol text-sm md:text-base">{ex.roman}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-2xl bg-coal border border-white/10 shadow-hard p-7 md:p-9 flex flex-col justify-center">
            <p className="font-cl text-paper-dim text-[11px] uppercase tracking-[0.2em]">
              Under the hood
            </p>
            <p className="mt-4 leading-relaxed text-paper-dim">
              Tuned Whisper models transcribe the vocals, force-alignment pins
              every word to the moment it is sung, and spelling rules tuned for
              Hindi and Malayalam keep the English-letter view readable.
            </p>
            <p className="mt-4 leading-relaxed text-paper-dim">
              English songs get synced lyrics too — verified from LRCLIB when
              the song is found, transcribed when it isn&apos;t.
            </p>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="max-w-[1480px] mx-auto px-6 md:px-10 pb-20 md:pb-28">
        <p className="font-display text-3xl md:text-4xl">How it works</p>
        <div className="mt-10 grid gap-5 md:grid-cols-3">
          {STEPS.map((s) => (
            <div key={s.n} className="rounded-2xl bg-coal border border-white/10 shadow-hard-sm p-6">
              <p className="font-display text-4xl text-gold">{s.n}</p>
              <p className="mt-3 font-semibold text-lg">{s.title}</p>
              <p className="mt-2 text-sm leading-relaxed text-paper-dim">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Screenshots */}
      <section id="see" className="max-w-[1480px] mx-auto px-6 md:px-10 pb-20 md:pb-28">
        <p className="font-display text-3xl md:text-4xl">See it in action</p>
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          <div className="lg:col-span-2 rounded-2xl bg-coal border border-white/10 shadow-hard-sm p-4">
            <Image
              src="/screenshots/results-desktop.png"
              alt="Chordex results page: control panel on the left, chord sheet with chords placed over the lyrics on the right"
              width={900}
              height={568}
              className="rounded-xl w-full h-auto"
            />
            <p className="mt-3 text-sm text-paper-dim px-2">
              Playback controls on the left, the full chord sheet on the right.
            </p>
          </div>
          <div className="grid gap-5">
            <div className="rounded-2xl bg-coal border border-white/10 shadow-hard-sm p-4">
              <Image
                src="/screenshots/home.png"
                alt="Chordex upload page with a drop zone for audio files"
                width={600}
                height={400}
                className="rounded-xl w-full h-auto"
              />
              <p className="mt-3 text-sm text-paper-dim px-2">
                Drop a file, paste a link, pick a language.
              </p>
            </div>
            <div className="rounded-2xl bg-coal border border-white/10 shadow-hard-sm p-4">
              <Image
                src="/screenshots/results-mobile.png"
                alt="Chordex on mobile with a sticky now/next chord bar above the lyrics"
                width={300}
                height={400}
                className="rounded-xl w-full h-auto mx-auto max-w-[240px]"
              />
              <p className="mt-3 text-sm text-paper-dim px-2 text-center">
                Mobile keeps the live chord pinned while you read.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/10">
        <div className="max-w-[1480px] mx-auto px-6 md:px-10 py-10 flex flex-col md:flex-row items-center justify-between gap-6 text-sm text-paper-dim">
          <p className="font-display text-xl text-paper">Chordex</p>
          <p className="max-w-md text-center md:text-left leading-relaxed">
            Auto-generated chords — always trust your ear on complex tracks.
          </p>
          <div className="flex items-center gap-6 font-medium">
            <a
              href="https://github.com/anandude/chordex"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:opacity-55 transition-opacity"
            >
              GitHub
            </a>
            <span>MIT</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
