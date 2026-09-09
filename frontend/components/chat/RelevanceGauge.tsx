"use client";

import { useEffect, useRef } from "react";
import * as d3 from "d3";

interface RelevanceGaugeProps {
  /** Cosine similarity between the query and this passage, 0-1. */
  score: number;
  /** Overall width/height of the gauge in pixels. */
  size?: number;
}

// Similarity thresholds that decide the gauge's color. Tuned for cosine
// similarity on typical embedding models, where >0.7 is a strong match,
// 0.55-0.7 is a plausible-but-looser match, and below that the retrieved
// passage is probably only tangentially related.
const SUCCESS_THRESHOLD = 0.7;
const WARNING_THRESHOLD = 0.55;

const TRACK_WIDTH = 3.5;

/** Maps a similarity score to one of the app's existing status colors. */
function colorForScore(score: number): string {
  if (score >= SUCCESS_THRESHOLD) return "rgb(var(--success))";
  if (score >= WARNING_THRESHOLD) return "rgb(var(--warning))";
  return "rgb(var(--danger))";
}

/** Same thresholds as the gauge's color, exposed as a human label so other
 * components (e.g. CitationPanel) can describe a citation's real retrieval
 * confidence in words, consistently with what the gauge shows. */
export function confidenceLabel(score: number): "High confidence" | "Medium confidence" | "Low confidence" {
  if (score >= SUCCESS_THRESHOLD) return "High confidence";
  if (score >= WARNING_THRESHOLD) return "Medium confidence";
  return "Low confidence";
}

interface ArcDatum {
  endAngle: number;
}

/**
 * Small radial gauge showing a citation's retrieval-similarity score as a
 * ring that fills proportionally to the score (0 = empty ring, 1 = full
 * circle). Built with D3 (`d3.arc` + `d3.scaleLinear`) rather than plain
 * CSS/SVG because this is a genuinely data-bound visualization - unlike the
 * rest of the app's motion/decoration, the arc's sweep and color are both
 * direct functions of a real backend value (`similarity`).
 */
export default function RelevanceGauge({ score, size = 32 }: RelevanceGaugeProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const clamped = Math.max(0, Math.min(1, Number.isFinite(score) ? score : 0));

  useEffect(() => {
    if (!svgRef.current) return;

    const radius = size / 2;
    const innerRadius = Math.max(radius - TRACK_WIDTH, 1);
    const angleScale = d3.scaleLinear().domain([0, 1]).range([0, 2 * Math.PI]);
    const color = colorForScore(clamped);

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const group = svg
      .append("g")
      .attr("transform", `translate(${radius}, ${radius})`);

    // Background track: a full circle the value arc fills in against.
    const trackArc = d3
      .arc<ArcDatum>()
      .innerRadius(innerRadius)
      .outerRadius(radius)
      .cornerRadius(TRACK_WIDTH / 2)
      .startAngle(0)
      .endAngle(2 * Math.PI);

    group
      .append("path")
      .attr("d", trackArc({ endAngle: 2 * Math.PI }))
      .attr("fill", "rgb(var(--border))");

    // Foreground value arc, animated from 0 up to the real score on mount
    // via `d3.transition().attrTween(...)`, sweeping clockwise from the top.
    const valueArc = d3
      .arc<ArcDatum>()
      .innerRadius(innerRadius)
      .outerRadius(radius)
      .cornerRadius(TRACK_WIDTH / 2)
      .startAngle(0);

    group
      .append("path")
      .attr("fill", color)
      .datum<ArcDatum>({ endAngle: 0 })
      .transition()
      .duration(700)
      .ease(d3.easeCubicOut)
      .attrTween("d", function (d) {
        const interpolate = d3.interpolate(d.endAngle, angleScale(clamped));
        return (t: number) => {
          d.endAngle = interpolate(t);
          return valueArc(d) ?? "";
        };
      });
  }, [clamped, size]);

  const percentLabel = `${Math.round(clamped * 100)}%`;

  return (
    <div
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Relevance score ${percentLabel}`}
      title={`Relevance: ${percentLabel}`}
    >
      <svg ref={svgRef} width={size} height={size} />
      <span
        aria-hidden
        className="pointer-events-none absolute text-[9px] font-semibold tabular-nums"
        style={{ color: colorForScore(clamped) }}
      >
        {Math.round(clamped * 100)}
      </span>
    </div>
  );
}
