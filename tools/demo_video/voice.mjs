// Generate one narration file per shot and record how long each one lasts.
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { NARRATION, ORDER } from "./script.mjs";

mkdirSync("audio", { recursive: true });
const durations = {};
for (const id of ORDER) {
  const file = `audio/${id}.mp3`;
  if (!existsSync(file)) {
    execFileSync("python", ["-m", "edge_tts", "--voice", "en-US-AndrewNeural", "--rate=-4%", "--text", NARRATION[id], "--write-media", file], { stdio: "ignore" });
  }
  durations[id] = Number(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file]).toString());
  console.log(id, durations[id].toFixed(1));
}
writeFileSync("audio/durations.json", JSON.stringify(durations, null, 1));
console.log("total", Object.values(durations).reduce((a, b) => a + b, 0).toFixed(1));
