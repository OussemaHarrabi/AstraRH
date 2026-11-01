import Link from "next/link";
import { Logo } from "@/ui/Logo";

export default function DemoPage() {
  return (
    <main className="flex min-h-screen flex-col bg-night text-white">
      <header className="mx-auto flex h-16 w-full max-w-[1240px] items-center justify-between px-5">
        <Link href="/" className="flex items-center gap-2 text-[17px] font-[600] tracking-tight"><Logo size={24} /> AstraRH</Link>
        <Link href="/login" className="rounded-full px-3.5 py-1.5 text-[15px] text-white/90 transition-colors hover:bg-white/10">Log in</Link>
      </header>
      <div className="mx-auto flex w-full max-w-[1100px] flex-1 flex-col justify-center px-5 pb-12">
        <h1 className="text-[clamp(26px,3.4vw,40px)] font-[480] tracking-[-0.018em]">See a hiring day in AstraRH</h1>
        <video src="/demo.mp4" controls playsInline preload="metadata" className="mt-5 aspect-video w-full rounded-2xl border border-white/15 bg-black shadow-[0_30px_90px_-20px_rgb(0_0_0/70%)]" />
      </div>
    </main>
  );
}
