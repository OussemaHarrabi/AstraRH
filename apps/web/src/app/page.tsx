"use client";

import { AnimatePresence, motion, MotionConfig, useMotionValueEvent, useScroll, useTransform } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ComponentType, type FormEvent, useRef, useState } from "react";
import { AGENTS, Face } from "@/ui/Face";
import { Icon } from "@/ui/Icon";
import { Logo } from "@/ui/Logo";
import { AskLoop, FollowLoop, HeroProduct, HiddenText, InboxLoop, RankLoop, ReplyLoop, SlotLoop } from "@/ui/landing/loops";
import { Scene } from "@/ui/landing/Scene";

const FEATURES: { title: string; body: string; film: ComponentType }[] = [
  { title: "A ranked shortlist, with the proof", body: "Names and photos are hidden while scoring. Every point traces back to a sentence in the CV, and the same inputs always give the same score.", film: RankLoop },
  { title: "This morning's inbox, already sorted", body: "A daily digest by type and urgency. Legal threats, salary talks and visa questions always go to a person, whatever the model thinks.", film: InboxLoop },
  { title: "Replies drafted from one file only", body: "The drafter sees that candidate's file and nothing else, then waits. You edit, you approve, and only then does a separate process send it.", film: ReplyLoop },
  { title: "Follow-ups that know when to stop", body: "Quiet candidates get a reminder every three days, two at most. A reply, a rejection or a hire stops them at once.", film: FollowLoop },
  { title: "Interview times from real calendars", body: "Three free times are held so nobody else gets them. A reply like “Tuesday works” becomes a booking you approve, in French, Arabic or English.", film: SlotLoop },
  { title: "Policy answers with citations, or none", body: "Employees get the exact sentence from the policy they may read. If there's no source, it goes to HR rather than a confident guess.", film: AskLoop },
];

const STEPS = [
  { title: "An agent proposes", body: "Every action that touches a person becomes a proposal, with the exact content and the evidence behind it." },
  { title: "A person decides", body: "Approval binds to a hash of that content. Change one word and the approval is void. Rejecting or hiring takes two people and a password." },
  { title: "A separate process acts", body: "Only the executor can send anything, on its own network and database role. The act lands in a chain of hashes anyone can verify." },
];

const RESULTS = [
  ["Strong candidates in the top 10", "10 of 10"],
  ["Evidence quotes found word for word", "177 of 177"],
  ["Scores that replay exactly", "42 of 42"],
  ["Hidden-text attack vs its clean twin", "Same score"],
  ["Emails needing a person, caught", "8 of 8"],
  ["Restricted documents leaked", "0"],
  ["Interview replies read correctly, in 3 languages", "8 of 8"],
  ["Cost of one screening run", "$0.018"],
];

function Nav() {
  const { scrollY } = useScroll();
  const [solid, setSolid] = useState(false);
  useMotionValueEvent(scrollY, "change", (value) => setSolid(value > 40));
  return (
    <header className={`fixed inset-x-0 top-0 z-30 transition-colors duration-200 ${solid ? "bg-[#10142e]/80 backdrop-blur-md" : ""}`}>
      <div className="mx-auto flex h-16 max-w-[1240px] items-center gap-8 px-5 text-white">
        <Link href="/" className="flex items-center gap-2 text-[17px] font-[600] tracking-tight">
          <Logo size={24} /> AstraRH
        </Link>
        <nav aria-label="Sections" className="hidden items-center gap-6 text-[15px] text-white/80 md:flex">
          <a href="#work" className="transition-colors hover:text-white">Product</a>
          <a href="#crew" className="transition-colors hover:text-white">Agents</a>
          <a href="#trust" className="transition-colors hover:text-white">Trust</a>
          <a href="#results" className="transition-colors hover:text-white">Results</a>
        </nav>
        <div className="ml-auto flex items-center gap-2 text-[15px]">
          <Link href="/login" className="rounded-full px-3.5 py-1.5 text-white/90 transition-colors hover:bg-white/10">Log in</Link>
          <Link href="/signup" className="rounded-full bg-[#5468f0] px-4 py-1.5 font-[520] text-white transition-colors hover:bg-[#6a7cf5]">Request access</Link>
        </div>
      </div>
    </header>
  );
}

function Hero() {
  const router = useRouter();
  const section = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: section, offset: ["start start", "end end"] });
  const headline = useTransform(scrollYProgress, [0, 0.28], [1, 0]);
  const headlineY = useTransform(scrollYProgress, [0, 0.28], [0, -50]);
  const windowY = useTransform(scrollYProgress, [0, 0.7], ["58vh", "0vh"]);
  const windowScale = useTransform(scrollYProgress, [0, 0.7], [0.86, 1]);

  function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "");
    router.push(`/signup${email ? `?email=${encodeURIComponent(email)}` : ""}`);
  }

  return (
    <section ref={section} className="relative h-[240vh] bg-[#0d1029]">
      <div className="sticky top-0 h-screen overflow-hidden">
        <Scene progress={scrollYProgress} />
        <motion.div style={{ opacity: headline, y: headlineY }} className="relative z-10 mx-auto flex max-w-5xl flex-col items-center px-5 pt-[15vh] text-center text-white">
          <h1 className="text-[clamp(38px,6vw,68px)] leading-[1.04] font-[480] tracking-[-0.022em]">
            The agents do the work.
            <br />
            You make the calls.
          </h1>
          <p className="mt-5 max-w-xl text-[clamp(16px,1.6vw,20px)] leading-snug text-white/85">
            CVs, inbox, replies, interviews and policy questions, prepared by AI and decided by your HR team. Nothing leaves without a person.
          </p>
          <form onSubmit={start} className="mt-7 flex w-full max-w-md items-center gap-1.5 rounded-full border border-white/20 bg-white/10 p-1.5 backdrop-blur-md">
            <input
              name="email"
              type="email"
              aria-label="Work email"
              placeholder="Your work email"
              className="min-w-0 flex-1 bg-transparent px-3.5 text-[15px] text-white outline-none placeholder:text-white/60"
            />
            <button type="submit" className="h-9 rounded-full bg-[#5468f0] px-4 text-[15px] font-[520] whitespace-nowrap transition-colors hover:bg-[#6a7cf5]">
              Request access
            </button>
            <Link href="/demo" className="hidden h-9 items-center rounded-full bg-white/12 px-4 text-[15px] whitespace-nowrap transition-colors hover:bg-white/20 sm:flex">
              Watch demo
            </Link>
          </form>
        </motion.div>
        <motion.div style={{ y: windowY, scale: windowScale }} className="absolute inset-x-0 top-[8vh] z-20 mx-auto h-[84vh] w-[min(1180px,calc(100vw-32px))] origin-top">
          <div className="light-tokens h-full overflow-hidden rounded-2xl border border-white/15 bg-surface shadow-[0_40px_120px_-20px_rgb(0_0_0/70%)]">
            <div className="flex h-9 items-center gap-1.5 border-b border-line bg-plaster px-3.5">
              <span className="size-2.5 rounded-full bg-line-strong" />
              <span className="size-2.5 rounded-full bg-line-strong" />
              <span className="size-2.5 rounded-full bg-line-strong" />
            </div>
            <div className="h-[calc(100%-36px)]">
              <HeroProduct />
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

function Work() {
  const rail = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: rail, offset: ["start start", "end end"] });
  const [active, setActive] = useState(0);
  useMotionValueEvent(scrollYProgress, "change", (value) => {
    setActive(Math.min(FEATURES.length - 1, Math.floor(value * FEATURES.length)));
  });
  const Film = FEATURES[active].film;

  function jump(index: number) {
    const box = rail.current;
    if (!box) return;
    const top = box.getBoundingClientRect().top + window.scrollY;
    const travel = box.offsetHeight - window.innerHeight;
    window.scrollTo({ top: top + (travel * (index + 0.1)) / FEATURES.length, behavior: "smooth" });
  }

  return (
    <section id="work" ref={rail} className="relative h-[420vh] scroll-mt-0 bg-[#0d1029] text-white">
      <div className="sticky top-0 flex h-screen items-center overflow-hidden">
        <div className="mx-auto grid w-full max-w-[1240px] items-center gap-10 px-5 md:grid-cols-[minmax(300px,420px)_1fr]">
          <div>
            <h2 className="text-[clamp(28px,3.4vw,42px)] leading-[1.08] font-[480] tracking-[-0.018em]">Six jobs off your desk. Every decision still yours.</h2>
            <ul className="mt-7 border-t border-white/15">
              {FEATURES.map((feature, index) => (
                <li key={feature.title} className="border-b border-white/15">
                  <button type="button" onClick={() => jump(index)} className="w-full py-3 text-left">
                    <span className={`block text-[16px] font-[520] transition-colors duration-200 ${active === index ? "text-white" : "text-white/55 hover:text-white/80"}`}>
                      {feature.title}
                    </span>
                    <AnimatePresence initial={false}>
                      {active === index ? (
                        <motion.span
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.26, ease: [0.2, 0, 0, 1] }}
                          className="block overflow-hidden text-[15px] leading-snug text-white/70"
                        >
                          <span className="block pt-1.5">{feature.body}</span>
                        </motion.span>
                      ) : null}
                    </AnimatePresence>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className="light-tokens hidden h-[min(390px,66vh)] overflow-hidden rounded-2xl border border-white/15 bg-surface shadow-[0_30px_90px_-20px_rgb(0_0_0/70%)] md:block">
            <AnimatePresence mode="wait">
              <motion.div key={active} initial={{ opacity: 0, scale: 0.99 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.22 }} className="h-full">
                <Film />
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
}

function CrewSection() {
  const [picked, setPicked] = useState(AGENTS[1]);
  return (
    <section id="crew" className="bg-[#f6f7f9] py-24 text-[#1b1e2e]">
      <div className="mx-auto max-w-[1240px] px-5">
        <h2 className="max-w-2xl text-[clamp(28px,3.4vw,42px)] leading-[1.08] font-[480] tracking-[-0.018em]">Meet the crew. They prepare, you decide.</h2>
        <p className="mt-3 max-w-xl text-[17px] text-[#5b6075]">Eleven agents, each with one job and no way to act alone. In the app, a face shows what each one is doing right now.</p>
        <div className="mt-10 grid items-center gap-10 md:grid-cols-[1.2fr_1fr]">
          <div className="flex flex-wrap gap-2.5">
            {AGENTS.map((agent) => (
              <button
                key={agent.id}
                type="button"
                onMouseEnter={() => setPicked(agent)}
                onFocus={() => setPicked(agent)}
                aria-label={`${agent.name}: ${agent.role}`}
                className={`rounded-2xl p-2.5 transition-[background-color,transform] duration-150 hover:-translate-y-1 ${picked.id === agent.id ? "bg-white shadow-[0_8px_24px_-8px_rgb(27_30_46/18%)]" : ""}`}
              >
                <Face agent={agent} size={64} track mood={picked.id === agent.id ? "happy" : "idle"} />
              </button>
            ))}
          </div>
          <div className="min-h-32">
            <AnimatePresence mode="wait">
              <motion.div key={picked.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }}>
                <p className="text-[24px] font-[520] tracking-tight">{picked.name}</p>
                <p className="text-[#5b6075]">{picked.role}</p>
                <p className="mt-3 text-[17px] leading-snug">{picked.does}</p>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
}

function Trust() {
  return (
    <section id="trust" className="bg-white py-24 text-[#1b1e2e]">
      <div className="mx-auto max-w-[1240px] px-5">
        <h2 className="max-w-2xl text-[clamp(28px,3.4vw,42px)] leading-[1.08] font-[480] tracking-[-0.018em]">An AI can be talked into anything. So we don&rsquo;t let it act.</h2>
        <ol className="mt-12 grid gap-8 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="border-t-2 border-[#4254db] pt-4">
              <p className="tabular text-[15px] text-[#5b6075]">Step {index + 1}</p>
              <p className="mt-1 text-[20px] font-[520] tracking-tight">{step.title}</p>
              <p className="mt-2 text-[16px] leading-snug text-[#5b6075]">{step.body}</p>
            </li>
          ))}
        </ol>
        <div className="mt-20 grid items-center gap-10 rounded-3xl bg-[#10142e] p-6 text-white md:grid-cols-2 md:p-12">
          <div>
            <h3 className="text-[clamp(24px,2.6vw,34px)] leading-[1.1] font-[480] tracking-[-0.015em]">Some CVs are written for the machine.</h3>
            <p className="mt-3 max-w-md text-[16px] leading-snug text-white/75">
              White text, tiny text and off-page text are found and deleted from the file itself. What remains goes to a model with no tools, and only validated data comes out. In our tests, an attack CV scores exactly like its clean twin.
            </p>
          </div>
          <HiddenText />
        </div>
      </div>
    </section>
  );
}

function Results() {
  return (
    <section id="results" className="bg-white pb-24 text-[#1b1e2e]">
      <div className="mx-auto grid max-w-[1240px] gap-10 px-5 md:grid-cols-[1fr_1.4fr]">
        <div>
          <h2 className="text-[clamp(28px,3.4vw,42px)] leading-[1.08] font-[480] tracking-[-0.018em]">Measured with real model calls.</h2>
          <p className="mt-3 max-w-sm text-[16px] leading-snug text-[#5b6075]">From our evaluation suite, run against labelled test CVs and emails we wrote for this purpose. It runs again with one command.</p>
        </div>
        <dl className="border-t border-[#e4e6ec]">
          {RESULTS.map(([label, value]) => (
            <div key={label} className="flex items-baseline justify-between gap-6 border-b border-[#e4e6ec] py-3">
              <dt className="text-[16px] text-[#5b6075]">{label}</dt>
              <dd className="tabular text-[17px] font-[560] whitespace-nowrap">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <section className="bg-[#10142e] text-white">
      <div className="mx-auto max-w-[1240px] px-5 pt-24 pb-10">
        <h2 className="max-w-3xl text-[clamp(32px,4.6vw,56px)] leading-[1.04] font-[480] tracking-[-0.02em]">Hand over the paperwork. Keep the decisions.</h2>
        <div className="mt-8 flex flex-wrap gap-2.5 text-[15px]">
          <Link href="/signup" className="flex h-10 items-center gap-1.5 rounded-full bg-[#5468f0] px-5 font-[520] transition-colors hover:bg-[#6a7cf5]">Request access</Link>
          <Link href="/login" className="flex h-10 items-center rounded-full bg-white/10 px-5 transition-colors hover:bg-white/20">Log in</Link>
          <Link href="/demo" className="flex h-10 items-center gap-1.5 rounded-full px-3 text-white/80 transition-colors hover:text-white"><Icon name="send" size={14} /> Watch the demo</Link>
        </div>
        <div className="mt-20 flex flex-wrap items-center justify-between gap-3 border-t border-white/12 pt-5 text-[14px] text-white/55">
          <span className="flex items-center gap-2"><Logo size={18} /> AstraRH, built for the Astropreneur SupCom hackathon</span>
          <span>CDS Tunis is a fictional company. All people shown are fictional.</span>
        </div>
      </div>
    </section>
  );
}

export default function LandingPage() {
  return (
    <MotionConfig reducedMotion="user">
      <main className="bg-[#0d1029]">
        <Nav />
        <Hero />
        <Work />
        <CrewSection />
        <Trust />
        <Results />
        <Footer />
      </main>
    </MotionConfig>
  );
}
