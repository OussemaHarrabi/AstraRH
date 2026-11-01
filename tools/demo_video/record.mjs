// Record each shot in a real browser against the running stack. Usage: node record.mjs [ids]
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";
import { NARRATION, ORDER } from "./script.mjs";

const ROOT = "C:/Users/oussa/oussema/HACKATHONS/Astropreneur-Supcom";
const password = readFileSync(`${ROOT}/.env`, "utf8").split(/\r?\n/).find((l) => l.startsWith("DEMO_PASSWORD=")).split("=").slice(1).join("=").replace(/^"|"$/g, "");
const durations = JSON.parse(readFileSync("audio/durations.json", "utf8"));
const BASE = "http://127.0.0.1:8080";
const SIZE = { width: 1600, height: 900 };
mkdirSync("raw", { recursive: true });
const browser = await chromium.launch();

async function stateFor(email) {
  const file = `raw/state-${email.split("@")[0]}.json`;
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${BASE}/login`);
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL("**/overview");
  await context.storageState({ path: file });
  await context.close();
  return file;
}

// A visible pointer and spoken-word captions, added only while recording.
const OVERLAY = () => {
  const start = () => {
    if (document.getElementById("rec-cursor")) return;
    const cursor = document.createElement("div");
    cursor.id = "rec-cursor";
    cursor.style.cssText = "position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;width:22px;height:22px;transition:transform 60ms linear;filter:drop-shadow(0 2px 4px rgb(0 0 0/35%))";
    cursor.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 2l15 11-7 1 4 8-3 1-4-8-5 5z" fill="#fff" stroke="#10142e" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(cursor);
    window.addEventListener("mousemove", (event) => { cursor.style.transform = `translate(${event.clientX}px,${event.clientY}px)`; }, true);
    const caption = document.createElement("div");
    caption.id = "rec-caption";
    caption.style.cssText = "position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:2147483646;pointer-events:none;max-width:1040px;padding:9px 18px;border-radius:12px;background:rgb(16 20 46/86%);color:#fff;font:500 21px/1.3 'Instrument Sans Variable',sans-serif;text-align:center;opacity:0;transition:opacity 180ms";
    document.documentElement.appendChild(caption);
    window.__caption = (text) => { caption.textContent = text; caption.style.opacity = text ? 1 : 0; };
  };
  if (document.documentElement) start();
  else document.addEventListener("DOMContentLoaded", start);
};

function helpers(page) {
  let x = 800;
  let y = 450;
  const glide = async (toX, toY, ms = 650) => {
    const steps = Math.max(8, Math.round(ms / 16));
    for (let index = 1; index <= steps; index += 1) {
      const t = index / steps;
      const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
      await page.mouse.move(x + (toX - x) * eased, y + (toY - y) * eased);
      await page.waitForTimeout(ms / steps);
    }
    x = toX;
    y = toY;
  };
  const to = async (locator) => {
    const target = locator.first();
    await target.scrollIntoViewIfNeeded().catch(() => undefined);
    const box = await target.boundingBox();
    if (box) await glide(box.x + Math.min(box.width / 2, 200), box.y + box.height / 2);
    return target;
  };
  const camera = { s: 1, x: 0, y: 0, on: false };
  const apply = async () => {
    await page.evaluate(({ s, x, y }) => { document.body.style.transform = `translate(${x}px,${y}px) scale(${s})`; }, camera);
    await page.waitForTimeout(720);
  };
  const enable = async () => {
    camera.s = 1; camera.x = 0; camera.y = 0; camera.on = true;
    await page.addStyleTag({ content: "html{overflow:hidden;height:100%}body{height:100vh;overflow:auto;transform-origin:0 0;transition:transform 680ms cubic-bezier(.22,1,.36,1)}" });
  };
  const zoom = async (locator, scale = 1.75) => {
    const target = locator.first();
    await target.scrollIntoViewIfNeeded().catch(() => undefined);
    await page.waitForTimeout(80);
    const box = await target.boundingBox();
    if (!box) return;
    const cx = (box.x + box.width / 2 - camera.x) / camera.s;
    const cy = (box.y + box.height / 2 - camera.y) / camera.s;
    camera.s = scale;
    camera.x = Math.min(0, Math.max(SIZE.width * (1 - scale), SIZE.width / 2 - cx * scale));
    camera.y = Math.min(0, Math.max(SIZE.height * (1 - scale), SIZE.height / 2 - cy * scale));
    await apply();
  };
  const wide = async () => {
    camera.s = 1; camera.x = 0; camera.y = 0;
    await apply();
  };
  return {
    enable,
    zoom,
    wide,
    glide,
    wait: (ms) => page.waitForTimeout(ms),
    hover: to,
    click: async (locator) => {
      const target = await to(locator);
      await page.waitForTimeout(160);
      await target.click();
    },
    type: async (locator, text, delay = 34) => {
      const target = await to(locator);
      await target.click();
      await page.keyboard.type(text, { delay });
    },
    scroll: async (distance, ms = 2000) => {
      const steps = Math.round(ms / 16);
      const startY = await page.evaluate(() => window.scrollY + document.body.scrollTop);
      for (let index = 1; index <= steps; index += 1) {
        const t = index / steps;
        const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
        await page.evaluate((top) => { window.scrollTo(0, top); document.body.scrollTop = top; }, startY + distance * eased);
        await page.waitForTimeout(16);
      }
    },
  };
}

const USERS = { nadia: "nadia@cds.example.test", leila: "leila@cds.example.test", mehdi: "mehdi@cds.example.test", admin: "admin@cds.example.test", none: null };
const states = {};

const SHOTS = {
  hero: { user: "none", open: "/", run: async (page, h) => {
    await h.wait(5200);
    await h.scroll(800, 7000);
  } },
  work: { user: "none", open: "/", prepare: async (page) => {
    const top = await page.evaluate(() => document.getElementById("work").offsetTop);
    await page.evaluate((y) => window.scrollTo(0, y + 10), top);
    await page.waitForTimeout(600);
  }, run: async (page, h, total) => {
    const top = await page.evaluate(() => document.getElementById("work").offsetTop);
    const travel = await page.evaluate(() => document.getElementById("work").offsetHeight - window.innerHeight);
    for (let index = 0; index < 5; index += 1) {
      await h.wait((total - 1500) / 5 - 500);
      await h.scroll(travel / 6, 500);
    }
    return top;
  } },
  overview: { user: "nadia", open: "/overview", run: async (page, h) => {
    await h.enable();
    await h.wait(700);
    await h.zoom(page.getByText("Your crew").first(), 1.9);
    await h.glide(1150, 300, 700);
    await h.wait(2300);
    await h.wide();
    await h.zoom(page.getByText("Waiting for your decision"), 1.7);
    await h.hover(page.getByText(/^Reply to /).first());
    await h.wait(2300);
    await h.wide();
    await h.scroll(380, 1300);
  } },
  ranking: { user: "nadia", open: "@job:Backend Engineer", run: async (page, h) => {
    await h.enable();
    await h.wait(900);
    await h.hover(page.getByRole("heading", { name: "Backend Engineer" }));
    await h.wait(1500);
    await h.zoom(page.getByRole("button", { name: /Sofien Maatoug/ }), 1.8);
    await h.hover(page.getByRole("button", { name: /Sofien Maatoug/ }));
    await h.wait(3400);
    await h.wide();
    await h.scroll(420, 2200);
  } },
  why: { user: "nadia", open: "@job:Backend Engineer", run: async (page, h) => {
    await h.enable();
    await h.click(page.getByRole("button", { name: /Sofien Maatoug/ }));
    await h.wait(800);
    const dialog = page.getByRole("dialog");
    const quote = dialog.getByText("Built order-tracking microservices").first();
    await h.zoom(quote, 1.8);
    await h.hover(quote);
    await h.wait(1100);
    await h.wide();
    const button = dialog.getByRole("button", { name: "Recalculate score" });
    await button.scrollIntoViewIfNeeded();
    await h.zoom(button, 1.9);
    await h.click(button);
    await dialog.getByText("Exact match").waitFor({ timeout: 15000 });
    await h.hover(dialog.getByText("Exact match"));
    await h.wait(2000);
  } },
  attack: { user: "nadia", open: "@job:Backend Engineer", run: async (page, h) => {
    await h.enable();
    await h.wait(500);
    await h.click(page.getByText("Attacks flagged"));
    await h.wait(1200);
    await h.click(page.getByRole("button", { name: /Malek Karoui/ }));
    await h.wait(800);
    const dialog = page.getByRole("dialog");
    await h.click(dialog.getByRole("tab", { name: "CV as read" }));
    await h.wait(800);
    const flag = dialog.getByText(/found and removed/).first();
    await h.zoom(flag, 1.9);
    await h.hover(flag);
    await h.wait(3000);
    await h.wide();
    await h.wait(1200);
  } },
  criteria: { user: "nadia", open: "@job:Security Analyst", run: async (page, h) => {
    await h.enable();
    await h.click(page.getByRole("tab", { name: "Criteria" }));
    await h.wait(900);
    const first = page.locator('input[type="range"]').nth(0);
    const second = page.locator('input[type="range"]').nth(1);
    const up = Number(await second.inputValue());
    const down = Number(await first.inputValue());
    await h.zoom(second, 1.8);
    await h.hover(second);
    await second.fill(String(up + 3));
    await h.wait(400);
    await second.fill(String(up + 5));
    await h.wait(700);
    await h.hover(first);
    await first.fill(String(down - 3));
    await h.wait(400);
    await first.fill(String(down - 5));
    await h.wait(800);
    await h.wide();
    await h.hover(page.getByText(/Weights total/));
    await h.wait(1200);
  } },
  inbox: { user: "nadia", open: "/inbox", run: async (page, h) => {
    await h.enable();
    await h.wait(800);
    await h.hover(page.getByText("Need a person"));
    await h.wait(700);
    await h.click(page.getByRole("button", { name: /Your treatment of my application/ }));
    await h.wait(900);
    const tag = page.getByText("Needs a person").last();
    await h.zoom(tag, 1.9);
    await h.hover(tag);
    await h.wait(3000);
    await h.wide();
    await h.click(page.getByRole("button", { name: /Ignore previous instructions/ }));
    await h.wait(1500);
  } },
  reply: { user: "nadia", open: "/approvals", run: async (page, h) => {
    await h.enable();
    await h.wait(500);
    await h.click(page.getByRole("button", { name: /Reply to Olfa Rekik/ }));
    await h.wait(600);
    await h.zoom(page.getByText(/^To .*example\.test/).first(), 1.7);
    await h.wait(1500);
    await h.click(page.getByRole("button", { name: "Edit", exact: true }));
    await h.wait(400);
    const body = page.locator('textarea[name="body"]');
    await h.click(body);
    await page.keyboard.press("Control+End");
    await page.keyboard.type("\n\nNadia, CDS Tunis", { delay: 38 });
    await h.wait(400);
    await h.click(page.getByRole("button", { name: "Save changes" }));
    await h.wait(1000);
    const hash = page.getByText("Approval binds to this exact content");
    await h.zoom(hash, 1.9);
    await h.hover(hash);
    await h.wait(1000);
  } },
  send: { user: "nadia", open: "/approvals", run: async (page, h) => {
    await h.enable();
    await h.click(page.getByRole("button", { name: /Reply to Olfa Rekik/ }));
    await h.wait(300);
    const approve = page.getByRole("button", { name: "Approve", exact: true });
    await h.zoom(approve, 1.9);
    await h.click(approve);
    await h.wait(1900);
    await page.goto("http://127.0.0.1:8025/");
    await h.enable();
    await h.wait(900);
    await h.glide(1000, 84, 500);
    await h.wait(300);
    await page.mouse.click(1000, 84);
    await h.wait(700);
    await h.zoom(page.getByText("Nadia, CDS Tunis").first().or(page.getByText("Subject").first()), 1.6);
    await h.wait(1500);
  } },
  booking: { user: "nadia", open: "/interviews", run: async (page, h) => {
    await h.enable();
    await h.wait(500);
    const held = page.getByText("Held offer").first();
    await h.zoom(held, 1.8);
    await h.hover(held);
    await h.wait(1200);
    await page.goto(`${BASE}/approvals`);
    await h.enable();
    await h.wait(500);
    await h.click(page.getByRole("button", { name: /Book Nizar Hmida/ }));
    await h.wait(400);
    await h.click(page.getByRole("button", { name: "Why this suggestion?" }));
    await h.wait(700);
    const quote = page.getByText("Tuesday works for me").first();
    await h.zoom(quote, 1.9);
    await h.hover(quote);
    await h.wait(1200);
    await h.wide();
    const approve = page.getByRole("button", { name: "Approve", exact: true });
    await h.click(approve);
    await h.wait(2300);
    await page.goto(`${BASE}/interviews`);
    await h.enable();
    await h.wait(900);
    const booked = page.getByText("Interview: Backend Engineer").last();
    await h.zoom(booked, 1.8);
    await h.hover(booked);
    await h.wait(1200);
  } },
  ask: { user: "mehdi", open: "/ask", run: async (page, h) => {
    await h.enable();
    await h.wait(600);
    const question = page.getByText("How many days can I work from home?").first();
    await h.hover(question);
    await h.wait(500);
    const source = page.getByRole("button", { name: /Remote work policy/ }).first();
    await h.click(source);
    await h.wait(500);
    await h.zoom(source, 1.8);
    await h.hover(source);
    await h.wait(2000);
    await h.wide();
    const refusal = page.getByText(/passed it to HR/).first();
    await h.zoom(refusal, 1.8);
    await h.hover(refusal);
    await h.wait(2200);
  } },
  agents: { user: "nadia", open: "/agents", run: async (page, h) => {
    await h.enable();
    await h.wait(800);
    await h.click(page.getByRole("button", { name: /Nour/ }).first());
    await h.wait(1000);
    const dialog = page.getByRole("dialog");
    const run = dialog.locator("li button").first();
    await h.click(run);
    await h.wait(700);
    await h.zoom(dialog.getByText(/Justifier/).first(), 1.6);
    await h.wait(2600);
  } },
  graph: { user: "nadia", open: "/graph", run: async (page, h) => {
    await h.wait(800);
    await h.glide(820, 520, 900);
    await h.wait(700);
    await h.glide(760, 650, 800);
    await h.wait(900);
    await h.glide(1120, 400, 800);
    await h.wait(500);
    await h.click(page.getByRole("tab", { name: "Agents and decisions" }));
    await h.wait(1800);
    await h.glide(760, 520, 1000);
    await h.wait(900);
    await h.glide(1000, 640, 1000);
    await h.wait(900);
  } },
  payroll: { user: "admin", open: "/onboarding", run: async (page, h) => {
    await h.wait(1500);
    await page.goto(`${BASE}/payroll`);
    await h.enable();
    await h.wait(700);
    await h.click(page.locator("tbody tr").first());
    await h.wait(1500);
    await page.keyboard.press("Escape");
    await page.goto(`${BASE}/approvals`);
    await h.enable();
    await h.wait(400);
    await h.click(page.getByRole("button", { name: /Approve the payroll run/ }));
    await h.wait(400);
    const rule = page.getByText("Needs two different people");
    await h.zoom(rule, 1.8);
    await h.hover(rule);
    await h.wait(600);
    await h.wide();
    await h.click(page.getByRole("button", { name: "Approve", exact: true }));
    const box = page.locator('input[name="password"]');
    await box.waitFor({ timeout: 6000 });
    await h.zoom(box, 1.9);
    await h.wait(1300);
    await h.wide();
    await h.click(page.getByRole("button", { name: "Cancel", exact: true }));
  } },
  audit: { user: "leila", open: "/audit", run: async (page, h) => {
    await h.enable();
    await h.wait(800);
    const verify = page.getByRole("button", { name: "Verify the chain" });
    await h.zoom(verify, 1.7);
    await h.click(verify);
    const result = page.getByText(/Verified: all/);
    await result.waitFor({ timeout: 15000 });
    await h.zoom(result, 1.7);
    await h.wait(2000);
    await h.wide();
    await h.click(page.locator("main li button").nth(2));
    await h.wait(1100);
  } },
  close: { user: "none", open: "/", prepare: async (page) => {
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(800);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(600);
  }, run: async (page, h) => { await h.wait(2500); } },
};

async function jobHref(page, title) {
  const jobs = await page.evaluate(async () => (await fetch("/api/packs/talent/jobs")).json());
  return `/jobs/${jobs.find((job) => job.title === title).id}`;
}

const wanted = process.argv[2]?.split(",") ?? ORDER;
const log = existsLog();
for (const id of wanted) {
  const shot = SHOTS[id];
  const user = USERS[shot.user];
  if (user && !states[shot.user]) states[shot.user] = await stateFor(user);
  const context = await browser.newContext({
    viewport: SIZE,
    colorScheme: "light",
    storageState: user ? states[shot.user] : undefined,
    recordVideo: { dir: `raw/${id}`, size: SIZE },
  });
  await context.addInitScript(OVERLAY);
  const born = Date.now();
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  await page.goto(`${BASE}/login`).catch(() => undefined);
  let href = shot.open;
  if (href.startsWith("@job:")) href = await jobHref(page, href.slice(5));
  await page.goto(`${BASE}${href}`);
  await page.waitForTimeout(2600);
  await page.mouse.move(800, 450);
  if (shot.prepare) await shot.prepare(page);
  const startAt = (Date.now() - born) / 1000;
  const total = durations[id] * 1000;
  const sentences = NARRATION[id].match(/[^.!?]+[.!?]+/g).map((text) => text.trim());
  const chars = sentences.reduce((sum, text) => sum + text.length, 0);
  const captions = (async () => {
    for (const text of sentences) {
      await page.evaluate((value) => window.__caption?.(value), text).catch(() => undefined);
      await new Promise((resolve) => setTimeout(resolve, (text.length / chars) * total));
    }
    await page.evaluate(() => window.__caption?.("")).catch(() => undefined);
  })();
  let failure = null;
  await shot.run(page, helpers(page), total).catch((error) => { failure = error.message.slice(0, 300); });
  await captions;
  await page.waitForTimeout(500);
  const length = (Date.now() - born) / 1000;
  const video = page.video();
  await context.close();
  const path = await video.path();
  renameSync(path, `raw/${id}.webm`);
  rmSync(`raw/${id}`, { recursive: true, force: true });
  log[id] = { startAt, length };
  writeFileSync("raw/timing.json", JSON.stringify(log, null, 1));
  console.log(id, `voice ${durations[id].toFixed(1)}s, shot ${(length - startAt).toFixed(1)}s`, failure ? `FAILED: ${failure}` : "ok");
}
await browser.close();

function existsLog() {
  try {
    return JSON.parse(readFileSync("raw/timing.json", "utf8"));
  } catch {
    return {};
  }
}
