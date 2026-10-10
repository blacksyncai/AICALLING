"use client";

import { useId } from "react";

export function LogoMark({ className = "h-7 w-7" }: { className?: string }) {
  // Unique per instance: the logo renders in both the mobile and desktop bars,
  // and a gradient defined inside a hidden copy would not paint.
  const gid = `bs-mark-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#D2522B" />
          <stop offset="0.55" stopColor="#F97316" />
          <stop offset="1" stopColor="#F59E0B" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill={`url(#${gid})`} />
      <path
        d="M22 16h13c6.1 0 10 3.3 10 8.4 0 3.3-1.8 5.7-4.7 6.9 3.6 1 5.9 3.7 5.9 7.6 0 5.6-4.2 9.1-11 9.1H22V16zm12.2 12.6c2.6 0 4.2-1.3 4.2-3.5s-1.6-3.4-4.2-3.4h-5.4v6.9h5.4zm.7 13.3c2.8 0 4.5-1.4 4.5-3.8 0-2.3-1.7-3.7-4.5-3.7h-6.1v7.5h6.1z"
        fill="#ffffff"
      />
    </svg>
  );
}

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <LogoMark />
      <span className="font-display text-[16px] font-semibold tracking-tight">BlackSync</span>
    </span>
  );
}
