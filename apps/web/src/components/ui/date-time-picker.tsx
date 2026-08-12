import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { cn } from "../../lib/cn";
import { selectContentStyles, selectTriggerStyles } from "./select";

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function parseLocalDateTime(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match;
  const parsed = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
  );
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function toLocalDateTime(date: Date, time: string) {
  const normalizedTime = /^([01]\d|2[0-3]):[0-5]\d$/.test(time) ? time : "00:00";
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${normalizedTime}`;
}

function sameDay(left: Date | null, right: Date) {
  return Boolean(
    left &&
      left.getFullYear() === right.getFullYear() &&
      left.getMonth() === right.getMonth() &&
      left.getDate() === right.getDate(),
  );
}

function calendarDays(month: Date) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const mondayOffset = (first.getDay() + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayOffset);
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

function displayValue(value: string) {
  const parsed = parseLocalDateTime(value);
  if (!parsed) return null;
  return `${parsed.getFullYear()}/${pad(parsed.getMonth() + 1)}/${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

export function DateTimePicker({
  value,
  onValueChange,
  ariaLabel,
  placeholder,
  className,
  disabled,
}: {
  value: string;
  onValueChange: (value: string) => void;
  ariaLabel: string;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}) {
  const selected = parseLocalDateTime(value);
  const [month, setMonth] = useState(
    () => new Date(selected?.getFullYear() ?? new Date().getFullYear(), selected?.getMonth() ?? new Date().getMonth(), 1),
  );
  const [time, setTime] = useState(
    selected ? `${pad(selected.getHours())}:${pad(selected.getMinutes())}` : "00:00",
  );
  const [timeDraft, setTimeDraft] = useState(time);
  const days = useMemo(() => calendarDays(month), [month]);
  const today = new Date();

  useEffect(() => {
    const next = parseLocalDateTime(value);
    if (!next) return;
    const nextTime = `${pad(next.getHours())}:${pad(next.getMinutes())}`;
    setTime(nextTime);
    setTimeDraft(nextTime);
  }, [value]);

  function updateTime(nextTime: string) {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(nextTime)) {
      setTimeDraft(time);
      return;
    }
    setTime(nextTime);
    setTimeDraft(nextTime);
    if (selected) onValueChange(toLocalDateTime(selected, nextTime));
  }

  function chooseDate(date: Date) {
    onValueChange(toLocalDateTime(date, time));
  }

  function chooseNow() {
    const now = new Date();
    const nextTime = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
    setMonth(new Date(now.getFullYear(), now.getMonth(), 1));
    setTime(nextTime);
    setTimeDraft(nextTime);
    onValueChange(toLocalDateTime(now, nextTime));
  }

  return (
    <DropdownMenu.Root
      onOpenChange={(open) => {
        if (!open) return;
        const next = parseLocalDateTime(value) ?? new Date();
        setMonth(new Date(next.getFullYear(), next.getMonth(), 1));
      }}
    >
      <DropdownMenu.Trigger asChild disabled={disabled}>
        <button
          type="button"
          aria-label={ariaLabel}
          className={cn(selectTriggerStyles, "h-11", className)}
        >
          <span className="flex min-w-0 items-center gap-2.5">
            <CalendarDays size={16} className="shrink-0 text-violet-500" />
            <span
              className={cn(
                "truncate tabular-nums",
                !displayValue(value) && "text-[var(--muted)]",
              )}
            >
              {displayValue(value) || placeholder || "选择日期时间"}
            </span>
          </span>
          <ChevronDown
            size={15}
            className="shrink-0 text-[var(--muted)] transition-transform duration-200 group-data-[state=open]:rotate-180"
          />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={7}
          collisionPadding={12}
          className={cn(selectContentStyles, "w-[19rem] overflow-visible p-3")}
          onCloseAutoFocus={(event) => event.preventDefault()}
        >
          <div className="flex items-center justify-between px-1 pb-3">
            <DropdownMenu.Item asChild onSelect={(event) => event.preventDefault()}>
              <button
                type="button"
                aria-label="上个月"
                className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted)] outline-none hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
                onClick={() =>
                  setMonth((current) =>
                    new Date(current.getFullYear(), current.getMonth() - 1, 1),
                  )
                }
              >
                <ChevronLeft size={16} />
              </button>
            </DropdownMenu.Item>
            <span className="text-sm font-semibold tabular-nums">
              {month.getFullYear()} 年 {month.getMonth() + 1} 月
            </span>
            <DropdownMenu.Item asChild onSelect={(event) => event.preventDefault()}>
              <button
                type="button"
                aria-label="下个月"
                className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted)] outline-none hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
                onClick={() =>
                  setMonth((current) =>
                    new Date(current.getFullYear(), current.getMonth() + 1, 1),
                  )
                }
              >
                <ChevronRight size={16} />
              </button>
            </DropdownMenu.Item>
          </div>
          <div className="grid grid-cols-7 gap-1 px-0.5 text-center">
            {WEEKDAYS.map((weekday) => (
              <span key={weekday} className="py-1 text-[11px] font-medium text-[var(--muted)]">
                {weekday}
              </span>
            ))}
            {days.map((day) => {
              const active = sameDay(selected, day);
              const currentMonth = day.getMonth() === month.getMonth();
              return (
                <DropdownMenu.Item
                  key={day.toISOString()}
                  asChild
                  onSelect={(event) => event.preventDefault()}
                >
                  <button
                    type="button"
                    aria-label={`${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`}
                    className={cn(
                      "relative flex h-9 items-center justify-center rounded-xl text-xs tabular-nums outline-none transition-colors",
                      currentMonth
                        ? "text-[var(--text)] hover:bg-violet-500/10"
                        : "text-[var(--muted)] opacity-45 hover:opacity-75",
                      sameDay(today, day) && !active && "font-bold text-violet-500",
                      active && "bg-violet-500 font-semibold text-white shadow-sm hover:bg-violet-600",
                    )}
                    onClick={() => chooseDate(day)}
                  >
                    {day.getDate()}
                    {active && <Check size={10} className="absolute right-0.5 top-0.5" />}
                  </button>
                </DropdownMenu.Item>
              );
            })}
          </div>
          <div className="mt-3 flex items-center gap-2 border-t border-[var(--border)] pt-3">
            <Clock3 size={15} className="ml-1 shrink-0 text-violet-500" />
            <input
              aria-label={`${ariaLabel}时间`}
              inputMode="numeric"
              className="h-9 min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 text-sm tabular-nums outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/15"
              value={timeDraft}
              placeholder="HH:mm"
              onChange={(event) => setTimeDraft(event.target.value)}
              onBlur={() => updateTime(timeDraft)}
              onKeyDown={(event) => {
                event.stopPropagation();
                if (event.key === "Enter") {
                  event.preventDefault();
                  updateTime(timeDraft);
                }
              }}
            />
            <DropdownMenu.Item
              className="cursor-pointer rounded-xl px-3 py-2 text-xs font-medium text-violet-600 outline-none hover:bg-violet-500/10 dark:text-violet-300"
              onSelect={(event) => {
                event.preventDefault();
                chooseNow();
              }}
            >
              现在
            </DropdownMenu.Item>
            {value && (
              <DropdownMenu.Item
                className="cursor-pointer rounded-xl px-3 py-2 text-xs font-medium text-[var(--muted)] outline-none hover:bg-[var(--surface-hover)]"
                onSelect={() => onValueChange("")}
              >
                清除
              </DropdownMenu.Item>
            )}
          </div>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export { calendarDays, displayValue, parseLocalDateTime, toLocalDateTime };
