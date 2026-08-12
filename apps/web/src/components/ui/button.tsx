import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

const buttonVariants = cva(
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-xl border border-transparent text-sm font-semibold transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/35 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--canvas)] active:scale-[.98] disabled:pointer-events-none disabled:opacity-45 disabled:shadow-none",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--brand)] text-white shadow-[0_1px_2px_rgba(40,25,90,.18),0_7px_20px_rgba(109,79,232,.16)] hover:bg-[var(--brand-strong)] hover:shadow-[0_2px_4px_rgba(40,25,90,.18),0_10px_24px_rgba(109,79,232,.2)]",
        secondary:
          "border-[var(--border)] bg-[var(--surface)] text-[var(--text)] shadow-[0_1px_2px_rgba(20,20,30,.04)] hover:border-violet-400/40 hover:bg-[var(--surface-hover)]",
        ghost:
          "text-[var(--muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
        danger: "bg-red-600 text-white shadow-sm hover:bg-red-700",
      },
      size: {
        default: "h-11 px-4",
        icon: "h-10 w-10 p-0",
        sm: "h-9 rounded-xl px-3 text-xs",
      },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

type Props = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean };

export function Button({ asChild, className, variant, size, ...props }: Props) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
