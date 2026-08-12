import { cn } from "../lib/cn";

export function Logo({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <svg
        aria-hidden="true"
        className="h-8 w-8 shrink-0"
        viewBox="0 0 32 32"
        fill="none"
      >
        <path
          d="M7 8.5C11 3.7 20 4.3 21.5 9.8C23 15.1 9.7 15.1 11 21.1C12.2 26.4 21.3 27.8 25.3 22.7"
          stroke="url(#synapse-gradient)"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <circle cx="7" cy="8.5" r="3" fill="#8467F4" />
        <circle cx="21.5" cy="9.8" r="2.6" fill="#24D6D1" />
        <circle cx="11" cy="21.1" r="2.6" fill="#8467F4" />
        <circle cx="25.3" cy="22.7" r="3" fill="#24D6D1" />
        <defs>
          <linearGradient id="synapse-gradient" x1="5" y1="5" x2="27" y2="27">
            <stop stopColor="#8467F4" />
            <stop offset="1" stopColor="#24D6D1" />
          </linearGradient>
        </defs>
      </svg>
      <div className="leading-none">
        <div className="font-semibold tracking-[-0.025em] text-[var(--text)]">SynapseKB</div>
        <div className="mt-1 text-[10px] tracking-[.24em] text-[var(--muted)]">触智</div>
      </div>
    </div>
  );
}
