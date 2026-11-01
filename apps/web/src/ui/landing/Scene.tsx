"use client";

import { motion, type MotionValue, useTransform } from "motion/react";

/**
 * Dusk over the Gulf of Tunis: Bou Kornine's two horns across the water, and Sidi Bou Said's
 * white walls and blue doors in front. Drawn, so it stays sharp at any size and weighs nothing.
 */

const STARS = Array.from({ length: 90 }, (_, index) => {
  const x = (index * 467.3) % 1600;
  const y = (index * 131.7) % 360;
  return { x, y, r: 0.5 + ((index * 7) % 10) / 12, o: 0.25 + ((index * 13) % 10) / 14 };
});

export function Scene({ progress }: { progress: MotionValue<number> }) {
  const far = useTransform(progress, [0, 1], [0, 40]);
  const near = useTransform(progress, [0, 1], [0, 150]);
  const nearScale = useTransform(progress, [0, 1], [1, 1.14]);
  const dim = useTransform(progress, [0.15, 0.85], [0, 0.82]);
  const stars = useTransform(progress, [0, 0.7], [0.75, 1]);

  return (
    <div aria-hidden className="absolute inset-0 overflow-hidden">
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(180deg,#111539 0%,#1c2055 26%,#3b3674 44%,#7f5484 57%,#d07c74 66%,#f4a96d 71%,#f8c48a 73%,#47406f 73.4%,#272654 84%,#15173a 100%)",
        }}
      />
      <motion.svg className="absolute inset-0 size-full" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" style={{ opacity: stars }}>
        {STARS.map((star) => (
          <circle key={`${star.x}-${star.y}`} cx={star.x} cy={star.y} r={star.r} fill="#fff" opacity={star.o} />
        ))}
      </motion.svg>
      <div
        className="absolute inset-x-0 h-[46%]"
        style={{ top: "42%", background: "radial-gradient(55% 55% at 76% 62%, rgb(255 205 150 / 62%), transparent 70%)" }}
      />
      <motion.svg className="absolute inset-0 size-full" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" style={{ y: far }}>
        {/* Bou Kornine: the two horns */}
        <path
          transform="translate(250 0)"
          d="M560 662 C700 640 790 600 860 560 C884 546 898 512 914 510 C930 508 938 540 958 548 C976 556 986 520 1004 496 C1018 478 1032 500 1044 530 C1066 584 1160 626 1290 662 Z"
          fill="#5d4a7c"
        />
        <path d="M0 662 C160 646 330 636 520 662 Z" fill="#6a5383" opacity="0.8" />
        <path d="M1240 662 C1340 644 1480 640 1600 652 V662 Z" fill="#6a5383" opacity="0.8" />
        {/* Light on the water */}
        <g stroke="#ffd9ad" strokeLinecap="round" opacity="0.5">
          {[676, 690, 706, 724, 746, 772].map((y, index) => (
            <line key={y} x1={1240 - 34 * index - 40} x2={1240 + 34 * index + 40} y1={y} y2={y} strokeWidth={1.2 + index * 0.35}>
              <animate attributeName="opacity" values="0.35;0.9;0.35" dur={`${3 + index * 0.7}s`} repeatCount="indefinite" />
            </line>
          ))}
        </g>
      </motion.svg>
      <motion.svg
        className="absolute inset-0 size-full origin-bottom"
        viewBox="0 0 1600 900"
        preserveAspectRatio="xMidYMax slice"
        style={{ y: near, scale: nearScale }}
      >
        {/* Sidi Bou Said, its walls gone violet with the last of the light */}
        <path
          d="M0 900 V740 h70 v-34 h26 c0-20 44-20 44 0 h60 v48 h78 v-30 h90 v44 h70 l60 80 V900 Z"
          fill="#231f4a"
        />
        <path d="M1180 900 V790 h70 v-44 h96 v-40 c0-34 74-34 74 0 v30 h70 v-60 h110 V900 Z" fill="#231f4a" />
        <path d="M1346 706 c0-34 74-34 74 0 z" fill="#3a3166" />
        {/* Doors and windows, still lit */}
        <g fill="#ffcf8f">
          <path d="M112 742 v-16 a8 8 0 0 1 16 0 v16 z" />
          <path d="M1370 760 v-20 a10 10 0 0 1 20 0 v20 z" />
          <path d="M1490 738 v-14 a7 7 0 0 1 14 0 v14 z" />
          <rect x="262" y="760" width="12" height="16" rx="6" />
          <rect x="300" y="760" width="12" height="16" rx="6" />
        </g>
        <path d="M1232 900 v-58 a20 20 0 0 1 40 0 v58 z" fill="#4254db" />
        <circle cx="1262" cy="868" r="2.200" fill="#ffcf8f" />
        {/* Bougainvillea over the wall */}
        <g fill="#c43a80">
          <circle cx="1204" cy="794" r="15" />
          <circle cx="1226" cy="782" r="19" />
          <circle cx="1254" cy="780" r="13" />
          <circle cx="1183" cy="808" r="10" />
        </g>
      </motion.svg>
      <motion.div className="absolute inset-0 bg-[#0d1029]" style={{ opacity: dim }} />
    </div>
  );
}
