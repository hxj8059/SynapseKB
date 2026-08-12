import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown } from "lucide-react";

import { cn } from "../../lib/cn";

export type SelectOption = {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
};

type SharedProps = {
  options: SelectOption[];
  placeholder?: string;
  ariaLabel: string;
  disabled?: boolean;
  className?: string;
  size?: "default" | "sm";
};

export const selectTriggerStyles =
  "group inline-flex w-full min-w-0 items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 text-left text-sm text-[var(--text)] shadow-[0_1px_2px_rgba(20,20,30,.03),inset_0_1px_0_rgba(255,255,255,.55)] outline-none transition-all hover:border-violet-400/45 hover:bg-[var(--surface-hover)] focus-visible:border-violet-500 focus-visible:ring-2 focus-visible:ring-violet-500/15 data-[state=open]:border-violet-500 data-[state=open]:ring-2 data-[state=open]:ring-violet-500/15 disabled:cursor-not-allowed disabled:opacity-50";

export const selectContentStyles =
  "synapse-select-content z-[100] max-h-[min(22rem,var(--radix-dropdown-menu-content-available-height))] min-w-[var(--radix-dropdown-menu-trigger-width)] overflow-x-hidden overflow-y-auto rounded-2xl border border-[var(--border)] bg-[color-mix(in_srgb,var(--surface)_96%,transparent)] p-1.5 text-[var(--text)] shadow-[0_18px_55px_rgba(20,18,35,.18),0_3px_12px_rgba(20,18,35,.08)] backdrop-blur-xl";

const itemStyles =
  "relative flex min-h-10 cursor-pointer select-none items-center gap-2.5 rounded-xl px-3 py-2 pr-9 text-sm outline-none transition-colors data-[disabled]:pointer-events-none data-[disabled]:opacity-40 data-[highlighted]:bg-violet-500/10 data-[highlighted]:text-[var(--text)]";

function TriggerContent({
  label,
  placeholder,
  count,
}: {
  label?: string;
  placeholder?: string;
  count?: number;
}) {
  return (
    <>
      <span
        className={cn(
          "min-w-0 flex-1 truncate",
          !label && "text-[var(--muted)]",
        )}
      >
        {label || placeholder || "请选择"}
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {count !== undefined && count > 1 && (
          <span className="rounded-full bg-violet-500/10 px-2 py-0.5 text-[11px] font-semibold text-violet-600 dark:text-violet-300">
            {count}
          </span>
        )}
        <ChevronDown
          aria-hidden="true"
          size={15}
          className="text-[var(--muted)] transition-transform duration-200 group-data-[state=open]:rotate-180"
        />
      </span>
    </>
  );
}

function ItemLabel({ option }: { option: SelectOption }) {
  return (
    <span className="min-w-0 flex-1">
      <span className="block truncate font-medium">{option.label}</span>
      {option.description && (
        <span className="mt-0.5 block truncate text-xs text-[var(--muted)]">
          {option.description}
        </span>
      )}
    </span>
  );
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder,
  ariaLabel,
  disabled,
  className,
  size = "default",
}: SharedProps & {
  value: string;
  onValueChange: (value: string) => void;
}) {
  const selected = options.find((option) => option.value === value);

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild disabled={disabled}>
        <button
          type="button"
          aria-label={ariaLabel}
          className={cn(
            selectTriggerStyles,
            size === "sm" ? "h-9 rounded-lg px-3 text-xs" : "h-11",
            className,
          )}
        >
          <TriggerContent label={selected?.label} placeholder={placeholder} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={7}
          collisionPadding={12}
          className={selectContentStyles}
        >
          <DropdownMenu.RadioGroup value={value} onValueChange={onValueChange}>
            {options.map((option) => (
              <DropdownMenu.RadioItem
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                className={itemStyles}
              >
                <ItemLabel option={option} />
                <DropdownMenu.ItemIndicator className="absolute right-3 flex h-5 w-5 items-center justify-center rounded-full bg-violet-500 text-white">
                  <Check size={12} strokeWidth={3} />
                </DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
          {options.length === 0 && (
            <div className="px-3 py-5 text-center text-sm text-[var(--muted)]">
              暂无可选项
            </div>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function MultiSelect({
  value,
  onValueChange,
  options,
  placeholder,
  ariaLabel,
  disabled,
  className,
  size = "default",
}: SharedProps & {
  value: string[];
  onValueChange: (value: string[]) => void;
}) {
  const selected = options.filter((option) => value.includes(option.value));
  const summary =
    selected.length === 0
      ? undefined
      : selected.length <= 2
        ? selected.map((option) => option.label).join("、")
        : `${selected[0]?.label} 等 ${selected.length} 项`;

  function toggle(optionValue: string, checked: boolean) {
    onValueChange(
      checked
        ? [...new Set([...value, optionValue])]
        : value.filter((item) => item !== optionValue),
    );
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild disabled={disabled}>
        <button
          type="button"
          aria-label={ariaLabel}
          className={cn(
            selectTriggerStyles,
            size === "sm" ? "h-9 rounded-lg px-3 text-xs" : "h-11",
            className,
          )}
        >
          <TriggerContent
            label={summary}
            placeholder={placeholder}
            count={selected.length}
          />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={7}
          collisionPadding={12}
          className={selectContentStyles}
          onCloseAutoFocus={(event) => event.preventDefault()}
        >
          <div className="flex items-center justify-between gap-3 px-3 pb-1.5 pt-1 text-xs text-[var(--muted)]">
            <span>{selected.length > 0 ? `已选择 ${selected.length} 项` : "选择一个或多个选项"}</span>
            {selected.length > 0 && (
              <DropdownMenu.Item
                className="cursor-pointer rounded-lg px-2 py-1 font-medium text-violet-600 outline-none hover:bg-violet-500/10 dark:text-violet-300"
                onSelect={() => onValueChange([])}
              >
                清除
              </DropdownMenu.Item>
            )}
          </div>
          <DropdownMenu.Separator className="mb-1 h-px bg-[var(--border)]" />
          {options.map((option) => (
            <DropdownMenu.CheckboxItem
              key={option.value}
              checked={value.includes(option.value)}
              disabled={option.disabled}
              className={itemStyles}
              onCheckedChange={(checked) => toggle(option.value, checked === true)}
              onSelect={(event) => event.preventDefault()}
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-md border border-[var(--border)] bg-[var(--surface)] text-white">
                <DropdownMenu.ItemIndicator className="flex h-full w-full items-center justify-center bg-violet-500">
                  <Check size={12} strokeWidth={3} />
                </DropdownMenu.ItemIndicator>
              </span>
              <ItemLabel option={option} />
            </DropdownMenu.CheckboxItem>
          ))}
          {options.length === 0 && (
            <div className="px-3 py-5 text-center text-sm text-[var(--muted)]">
              暂无可选项
            </div>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
