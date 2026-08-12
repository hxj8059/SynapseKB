import { cn } from "../lib/cn";

const tones: Record<string, string> = {
  ready: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  succeeded: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  failed: "bg-red-500/10 text-red-600 dark:text-red-400",
  cancelled: "bg-zinc-500/10 text-zinc-500",
  queued: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  uploaded: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400",
  processing: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2.5 py-1 text-xs font-medium",
        tones[status] ?? tones.queued,
      )}
    >
      {status}
    </span>
  );
}
