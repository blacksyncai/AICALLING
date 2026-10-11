"use client";

import { motion, type Transition } from "motion/react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

/** Headline that slides in word by word (adapted from danielpetho/vertical-cut-reveal, words only). */
export function VerticalCutReveal({
  children,
  reverse = false,
  staggerDuration = 0.08,
  transition = { type: "spring", stiffness: 250, damping: 40 },
  containerClassName,
}: {
  children: string;
  reverse?: boolean;
  staggerDuration?: number;
  transition?: Transition;
  containerClassName?: string;
}) {
  const [go, setGo] = useState(false);
  useEffect(() => setGo(true), []);
  const words = children.split(" ");
  return (
    <span className={cn("flex flex-wrap whitespace-pre-wrap", containerClassName)}>
      <span className="sr-only">{children}</span>
      {words.map((w, i) => (
        <span key={i} aria-hidden className="inline-flex overflow-hidden">
          <motion.span
            className="inline-block"
            initial={{ y: reverse ? "-100%" : "100%" }}
            animate={go ? { y: 0 } : undefined}
            transition={{ ...transition, delay: i * staggerDuration }}
          >
            {w}
          </motion.span>
          {i < words.length - 1 && <span> </span>}
        </span>
      ))}
    </span>
  );
}
