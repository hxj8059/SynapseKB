import type { InputHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 text-sm text-[var(--text)] shadow-[inset_0_1px_0_rgba(20,20,30,.02)] outline-none transition-all placeholder:text-[var(--muted)] hover:border-violet-400/40 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/15",
        className,
      )}
      {...props}
    />
  );
}
