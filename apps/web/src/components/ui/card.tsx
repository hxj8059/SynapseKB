import { forwardRef, type HTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function Card({ className, ...props }, ref) {
    return (
      <div
        ref={ref}
        className={cn(
          "rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-[0_10px_35px_rgba(30,25,55,.05)]",
          className,
        )}
        {...props}
      />
    );
  },
);
