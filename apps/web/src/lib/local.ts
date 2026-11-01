"use client";

/**
 * Front-only storage for features the API does not have yet. Everything kept here lives in this
 * browser and nowhere else. docs/FRONTEND_ONLY.md lists each key and the endpoint it should become.
 */

import { useCallback, useSyncExternalStore } from "react";

const PREFIX = "astra.local.";
const listeners = new Set<() => void>();
const cache = new Map<string, { raw: string | null; value: unknown }>();

function read<T>(key: string, initial: T): T {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(PREFIX + key);
  } catch {
    return initial;
  }
  const hit = cache.get(key);
  if (hit && hit.raw === raw) return hit.value as T;
  let value = initial;
  if (raw !== null) {
    try {
      value = JSON.parse(raw) as T;
    } catch {
      value = initial;
    }
  }
  cache.set(key, { raw, value });
  return value;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLocal<T>(key: string, initial: T): [T, (next: T | ((previous: T) => T)) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => read(key, initial),
    () => initial,
  );
  const set = useCallback(
    (next: T | ((previous: T) => T)) => {
      const previous = read(key, initial);
      const resolved = typeof next === "function" ? (next as (p: T) => T)(previous) : next;
      try {
        window.localStorage.setItem(PREFIX + key, JSON.stringify(resolved));
      } catch {
        cache.set(key, { raw: null, value: resolved });
      }
      listeners.forEach((listener) => listener());
    },
    [key, initial],
  );
  return [value, set];
}

/** Stable empties, so useLocal's `initial` never changes between renders. */
export const EMPTY_MAP: Record<string, never> = {};
export const EMPTY_LIST: never[] = [];

export interface Note {
  id: string;
  author: string;
  text: string;
  at: string;
}

export interface Scorecard {
  id: string;
  author: string;
  ratings: Record<string, number>;
  verdict: "advance" | "hold" | "no";
  summary: string;
  at: string;
}

export function newId(): string {
  return Math.random().toString(36).slice(2, 10);
}
