"use client";

import { Blobatar } from "@blobatar/react";
import { cn } from "@/lib/utils";
import type { Voice } from "@/lib/types";
import "blobatar/motion.css";

type Identity = Pick<Voice, "id" | "family">;

/** A local illustration, not a speaker photo. Tones in one family share a face. */
export function VoiceAvatar({
  voice,
  className,
  animated = false,
}: {
  voice: Identity;
  className?: string;
  animated?: boolean;
}) {
  const seed = voice.family
    ? `voice-family:${voice.family}`
    : `voice:${voice.id}`;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "block h-11 w-11 shrink-0 overflow-hidden rounded-full",
        className,
      )}
      data-voice-avatar
    >
      {animated ? (
        <Blobatar
          name={seed}
          background="circle"
          animate="hover"
          className="h-full w-full"
        />
      ) : (
        <Blobatar
          name={seed}
          background="circle"
          alt=""
          className="h-full w-full"
        />
      )}
    </span>
  );
}
