"use client";

import { motion } from "motion/react";

/**
 * Hand-authored flow diagram for the landing page's "How it works" section:
 * Upload -> Ask -> Trust the citation. The connecting line draws itself in
 * via Framer Motion's `pathLength` prop, which reveals an SVG path by
 * animating its `stroke-dasharray`/`stroke-dashoffset` under the hood - the
 * standard path-reveal technique - rather than any pre-rendered/static
 * image. This is purely illustrative (no live data), which is why it's
 * built with Framer Motion rather than D3.
 */
export default function HowItWorksDiagram() {
  const nodeTransition = (delay: number) => ({
    duration: 0.4,
    delay,
    ease: "easeOut" as const,
  });

  return (
    <svg
      viewBox="0 0 600 140"
      className="mx-auto h-28 w-full max-w-2xl sm:h-32"
      fill="none"
      aria-hidden="true"
    >
      {/* Connecting line, drawn left to right as the section scrolls into view. */}
      <motion.line
        x1={70}
        y1={70}
        x2={530}
        y2={70}
        stroke="rgb(var(--border))"
        strokeWidth={2}
        strokeDasharray="7 7"
        initial={{ pathLength: 0, opacity: 0 }}
        whileInView={{ pathLength: 1, opacity: 1 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={{ duration: 1.1, ease: "easeInOut" }}
      />

      {/* Node 1: Upload */}
      <motion.g
        initial={{ opacity: 0, scale: 0.6 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={nodeTransition(0.1)}
        style={{ transformOrigin: "70px 70px" }}
      >
        <circle
          cx={70}
          cy={70}
          r={32}
          fill="rgb(var(--primary) / 0.1)"
          stroke="rgb(var(--primary))"
          strokeWidth={2}
        />
        <path
          d="M70 84V58m0 0-10 10m10-10 10 10M55 86h30"
          stroke="rgb(var(--primary))"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </motion.g>

      {/* Node 2: Ask */}
      <motion.g
        initial={{ opacity: 0, scale: 0.6 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={nodeTransition(0.55)}
        style={{ transformOrigin: "300px 70px" }}
      >
        <circle
          cx={300}
          cy={70}
          r={32}
          fill="rgb(var(--primary) / 0.1)"
          stroke="rgb(var(--primary))"
          strokeWidth={2}
        />
        <path
          d="M286 58h28a4 4 0 0 1 4 4v16a4 4 0 0 1-4 4h-12l-9 9v-9h-7a4 4 0 0 1-4-4V62a4 4 0 0 1 4-4Z"
          stroke="rgb(var(--primary))"
          strokeWidth={2}
          strokeLinejoin="round"
        />
      </motion.g>

      {/* Node 3: Trust the citation */}
      <motion.g
        initial={{ opacity: 0, scale: 0.6 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={nodeTransition(1)}
        style={{ transformOrigin: "530px 70px" }}
      >
        <circle
          cx={530}
          cy={70}
          r={32}
          fill="rgb(var(--success) / 0.1)"
          stroke="rgb(var(--success))"
          strokeWidth={2}
        />
        <path
          d="M516 71l9 9 17-19"
          stroke="rgb(var(--success))"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </motion.g>
    </svg>
  );
}
