// Cut each shot to its narration, fade between them, and join everything into one film.
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { ORDER } from "./script.mjs";

const timing = JSON.parse(readFileSync("raw/timing.json", "utf8"));
const durations = JSON.parse(readFileSync("audio/durations.json", "utf8"));
mkdirSync("cut", { recursive: true });
const list = [];
for (const id of ORDER) {
  const shot = timing[id];
  const available = shot.length - shot.startAt;
  // Shots that end on a result keep it on screen after the voice stops.
  const linger = ["booking", "payroll", "send"].includes(id) ? 6 : 2.5;
  const length = Math.max(durations[id] + 0.55, Math.min(available, durations[id] + linger));
  const out = `cut/${id}.mp4`;
  execFileSync("ffmpeg", [
    "-y", "-loglevel", "error",
    "-ss", String(shot.startAt), "-t", String(length), "-i", `raw/${id}.webm`,
    "-i", `audio/${id}.mp3`,
    "-filter_complex",
    `[0:v]fps=30,scale=1600:900:flags=lanczos,fade=t=in:st=0:d=0.3:color=0x10142e,fade=t=out:st=${(length - 0.35).toFixed(2)}:d=0.35:color=0x10142e,format=yuv420p[v];[1:a]adelay=120|120,apad,atrim=0:${length.toFixed(2)},aformat=sample_rates=44100:channel_layouts=stereo[a]`,
    "-map", "[v]", "-map", "[a]",
    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
    out,
  ]);
  list.push(`file '${out}'`);
  console.log(id, length.toFixed(1));
}
writeFileSync("cut/list.txt", list.join("\n").replaceAll("cut/", ""));
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "cut/list.txt", "-c", "copy", "-movflags", "+faststart", "demo.mp4"]);
console.log(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration,size", "-of", "csv=p=0", "demo.mp4"]).toString());
