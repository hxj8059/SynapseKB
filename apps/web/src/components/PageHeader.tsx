import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && (
          <div className="mb-2 text-xs font-semibold uppercase tracking-[.18em] text-violet-500">
            {eyebrow}
          </div>
        )}
        <h1 className="text-2xl font-semibold tracking-[-0.03em] sm:text-3xl">{title}</h1>
        {description && (
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted)]">
            {description}
          </p>
        )}
      </div>
      {actions}
    </header>
  );
}
