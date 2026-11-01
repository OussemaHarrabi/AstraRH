"use client";

import { forceCenter, forceCollide, forceLink, forceManyBody, forceRadial, forceSimulation, forceX, forceY, type Simulation, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import { useEffect, useRef, useState } from "react";

/** A living constellation: nodes settle by force, and small lights travel along the edges. */

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  size?: number;
  ring?: number;
  hue?: number;
  face?: boolean;
  data?: Record<string, unknown>;
}

export interface GraphEdge {
  from: string;
  to: string;
  label?: string;
  weight?: number;
}

type SimNode = GraphNode & SimulationNodeDatum & { x: number; y: number };
type SimLink = SimulationLinkDatum<SimNode> & { source: SimNode; target: SimNode; weight: number; label?: string; phase: number };

export function ForceGraph({
  nodes,
  edges,
  colors,
  height = 560,
  selected,
  onSelect,
  labelFrom,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  colors: Record<string, string>;
  height?: number;
  selected?: string | null;
  onSelect?: (node: GraphNode | null) => void;
  labelFrom?: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const view = useRef({ x: 0, y: 0, k: 1 });
  const hover = useRef<SimNode | null>(null);
  const dragging = useRef<{ node: SimNode | null; lastX: number; lastY: number; moved: boolean } | null>(null);
  const selectedRef = useRef(selected);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);

  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);

  useEffect(() => {
    const element = canvas.current;
    const wrapper = box.current;
    if (!element || !wrapper) return;
    const context = element.getContext("2d");
    if (!context) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const known = new Set(nodes.map((node) => node.id));
    const simNodes = nodes.map((node, index) => ({
      ...node,
      x: Math.cos(index * 2.4) * (40 + index * 3),
      y: Math.sin(index * 2.4) * (40 + index * 3),
    })) as SimNode[];
    const links = edges
      .filter((edge) => known.has(edge.from) && known.has(edge.to))
      .map((edge, index) => ({ source: edge.from, target: edge.to, weight: edge.weight ?? 1, label: edge.label, phase: (index * 0.137) % 1 }));

    const rings = nodes.some((node) => node.ring !== undefined);
    const neighbours = new Map<string, Set<string>>();
    const simulation: Simulation<SimNode, undefined> = forceSimulation(simNodes)
      .force("link", forceLink(links as unknown as SimLink[]).id((node) => (node as SimNode).id).distance((link) => 60 + ((link.source as SimNode).size ?? 6) + ((link.target as SimNode).size ?? 6)).strength(rings ? 0.08 : 0.4))
      .force("charge", forceManyBody().strength(rings ? -220 : -320))
      .force("center", forceCenter(0, 0).strength(0.05))
      .force("collide", forceCollide<SimNode>().radius((node) => (node.size ?? 6) + (rings ? 12 : 8)))
      .force("ring", forceRadial<SimNode>((node) => node.ring ?? 0, 0, 0).strength((node) => (node.ring === undefined ? 0 : 0.9)))
      .force("x", forceX<SimNode>(0).strength(rings ? 0 : 0.09))
      .force("y", forceY<SimNode>(0).strength(rings ? 0 : 0.13))
      .stop();
    // Settle before the first paint, then frame the picture, ignoring a few stragglers.
    simulation.tick(260);
    const spreads = simNodes.map((node) => Math.max(Math.abs(node.x) / (wrapper.clientWidth / 2), Math.abs(node.y) / (height / 2))).sort((a, b) => a - b);
    const extent = Math.max(0.01, spreads[Math.floor(spreads.length * 0.97)] ?? 0.01);
    view.current = { x: 0, y: 0, k: Math.min(1.5, 0.84 / extent) };
    simulation.alpha(0.03).alphaDecay(0.01).restart();
    const liveLinks = links as unknown as SimLink[];
    for (const link of liveLinks) {
      const a = link.source.id;
      const b = link.target.id;
      if (!neighbours.has(a)) neighbours.set(a, new Set());
      if (!neighbours.has(b)) neighbours.set(b, new Set());
      neighbours.get(a)?.add(b);
      neighbours.get(b)?.add(a);
    }

    let width = 0;
    let frame = 0;
    let running = true;

    function size() {
      const ratio = window.devicePixelRatio || 1;
      width = wrapper!.clientWidth;
      element!.width = width * ratio;
      element!.height = height * ratio;
      element!.style.width = `${width}px`;
      element!.style.height = `${height}px`;
      context!.setTransform(ratio, 0, 0, ratio, 0, 0);
    }
    size();
    const observer = new ResizeObserver(size);
    observer.observe(wrapper);

    const css = getComputedStyle(element);
    const token = (name: string) => css.getPropertyValue(name).trim();

    function draw(time: number) {
      if (!running) return;
      const ink = token("--ink");
      const soft = token("--ink-soft");
      const line = token("--line-strong");
      const surface = token("--surface");
      const door = token("--door");
      const { x: panX, y: panY, k } = view.current;
      context!.clearRect(0, 0, width, height);
      context!.save();
      context!.translate(width / 2 + panX, height / 2 + panY);
      context!.scale(k, k);

      const focus = hover.current?.id ?? selectedRef.current ?? null;
      const near = focus ? neighbours.get(focus) : null;
      const lit = (id: string) => !focus || id === focus || near?.has(id);

      for (const link of liveLinks) {
        const active = focus && (link.source.id === focus || link.target.id === focus);
        context!.globalAlpha = focus ? (active ? 0.9 : 0.08) : 0.5;
        context!.strokeStyle = active ? door : line;
        context!.lineWidth = (active ? 1.6 : 1) * Math.max(0.6, link.weight);
        context!.beginPath();
        context!.moveTo(link.source.x, link.source.y);
        context!.lineTo(link.target.x, link.target.y);
        context!.stroke();
        if (!reduced && (!focus || active)) {
          const t = (time / 2600 + link.phase) % 1;
          context!.globalAlpha = focus ? 1 : 0.55;
          context!.fillStyle = door;
          context!.beginPath();
          context!.arc(link.source.x + (link.target.x - link.source.x) * t, link.source.y + (link.target.y - link.source.y) * t, active ? 2 : 1.3, 0, Math.PI * 2);
          context!.fill();
        }
      }

      for (const node of simNodes) {
        const radius = node.size ?? 6;
        const shown = lit(node.id);
        context!.globalAlpha = shown ? 1 : 0.15;
        if (node.id === selectedRef.current || node.id === hover.current?.id) {
          context!.fillStyle = door;
          context!.globalAlpha = 0.18;
          context!.beginPath();
          context!.arc(node.x, node.y, radius + 6, 0, Math.PI * 2);
          context!.fill();
          context!.globalAlpha = 1;
        }
        const fill = node.hue !== undefined ? `oklch(0.68 0.13 ${node.hue})` : (colors[node.kind] ?? door);
        context!.fillStyle = fill;
        context!.strokeStyle = surface;
        context!.lineWidth = 2;
        context!.beginPath();
        context!.arc(node.x, node.y, radius, 0, Math.PI * 2);
        context!.fill();
        context!.stroke();
        if (node.face) {
          const blink = (time + node.x * 40) % 4800 < 130;
          context!.fillStyle = "#191c33";
          const w = radius * 1.34;
          const h = radius * 0.86;
          context!.beginPath();
          context!.roundRect(node.x - w / 2, node.y - h / 2, w, h, h / 2.2);
          context!.fill();
          context!.fillStyle = "#fff";
          for (const side of [-1, 1]) {
            context!.beginPath();
            context!.ellipse(node.x + (side * radius) / 2.9, node.y, radius * 0.13, blink ? radius * 0.02 : radius * 0.19, 0, 0, Math.PI * 2);
            context!.fill();
          }
        }
        if (shown && (radius >= (labelFrom ?? 9) || k > 1.6 || focus)) {
          context!.fillStyle = radius >= 9 ? ink : soft;
          context!.font = `${radius >= 12 ? 560 : 450} ${radius >= 12 ? 13 : 11.5}px "Instrument Sans Variable", sans-serif`;
          context!.textAlign = "center";
          context!.textBaseline = "top";
          context!.fillText(node.label.length > 26 ? `${node.label.slice(0, 25)}…` : node.label, node.x, node.y + radius + 4);
        }
      }
      context!.restore();
      frame = requestAnimationFrame(draw);
    }
    frame = requestAnimationFrame(draw);

    function toWorld(event: PointerEvent | WheelEvent) {
      const rect = element!.getBoundingClientRect();
      return {
        x: (event.clientX - rect.left - width / 2 - view.current.x) / view.current.k,
        y: (event.clientY - rect.top - height / 2 - view.current.y) / view.current.k,
      };
    }
    function pick(event: PointerEvent) {
      const point = toWorld(event);
      let best: SimNode | null = null;
      let distance = Infinity;
      for (const node of simNodes) {
        const gap = Math.hypot(node.x - point.x, node.y - point.y);
        if (gap < (node.size ?? 6) + 6 && gap < distance) {
          best = node;
          distance = gap;
        }
      }
      return best;
    }
    function onMove(event: PointerEvent) {
      const drag = dragging.current;
      if (drag) {
        const dx = event.clientX - drag.lastX;
        const dy = event.clientY - drag.lastY;
        if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
        drag.lastX = event.clientX;
        drag.lastY = event.clientY;
        if (drag.node) {
          const point = toWorld(event);
          drag.node.fx = point.x;
          drag.node.fy = point.y;
          simulation.alphaTarget(0.2).restart();
        } else {
          view.current.x += dx;
          view.current.y += dy;
        }
        return;
      }
      const found = pick(event);
      hover.current = found;
      element!.style.cursor = found ? "pointer" : "grab";
      if (found) {
        const rect = element!.getBoundingClientRect();
        setTip({ x: event.clientX - rect.left, y: event.clientY - rect.top, text: found.label });
      } else {
        setTip(null);
      }
    }
    function onDown(event: PointerEvent) {
      element!.setPointerCapture(event.pointerId);
      dragging.current = { node: pick(event), lastX: event.clientX, lastY: event.clientY, moved: false };
    }
    function onUp(event: PointerEvent) {
      const drag = dragging.current;
      dragging.current = null;
      if (!drag) return;
      if (drag.node) {
        drag.node.fx = null;
        drag.node.fy = null;
        simulation.alphaTarget(0);
      }
      if (!drag.moved) {
        const found = pick(event);
        onSelect?.(found);
      }
    }
    function onWheel(event: WheelEvent) {
      event.preventDefault();
      const rect = element!.getBoundingClientRect();
      const mouseX = event.clientX - rect.left - width / 2;
      const mouseY = event.clientY - rect.top - height / 2;
      const factor = Math.exp(-event.deltaY * 0.0012);
      const next = Math.min(4, Math.max(0.3, view.current.k * factor));
      const scale = next / view.current.k;
      view.current.x = mouseX - (mouseX - view.current.x) * scale;
      view.current.y = mouseY - (mouseY - view.current.y) * scale;
      view.current.k = next;
    }
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerdown", onDown);
    element.addEventListener("pointerup", onUp);
    element.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      running = false;
      cancelAnimationFrame(frame);
      simulation.stop();
      observer.disconnect();
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointerup", onUp);
      element.removeEventListener("wheel", onWheel);
    };
  }, [nodes, edges, colors, height, onSelect, labelFrom]);

  return (
    <div ref={box} className="relative w-full overflow-hidden" style={{ height }}>
      <canvas ref={canvas} role="img" aria-label={`Graph of ${nodes.length} items and ${edges.length} connections`} className="touch-none" />
      {tip ? (
        <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-lg bg-night px-2 py-1 text-xs whitespace-nowrap text-white" style={{ left: tip.x, top: tip.y - 12 }}>
          {tip.text}
        </div>
      ) : null}
    </div>
  );
}
