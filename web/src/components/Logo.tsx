export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-600">
        <svg viewBox="0 0 32 32" className="h-4 w-4" aria-hidden>
          <path d="M11 9.5c0-.8.9-1.3 1.6-.9l10.2 6.5c.6.4.6 1.4 0 1.8L12.6 23.4c-.7.4-1.6-.1-1.6-.9z" fill="#fff" />
        </svg>
      </span>
      <span className="text-[15px] font-semibold tracking-tight">Closer</span>
    </span>
  );
}
