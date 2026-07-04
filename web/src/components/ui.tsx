"use client";

import * as React from "react";
import { cn, pct, type Tone } from "@/lib/format";

/* ------------------------------------------------------------------ *
 * Button
 * ------------------------------------------------------------------ */

type ButtonVariant = "primary" | "ghost" | "quiet";
type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

const btnBase =
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium " +
  "whitespace-nowrap select-none cursor-pointer " +
  "transition-[transform,background-color,border-color,color,opacity] duration-150 " +
  "[transition-timing-function:var(--ease)] active:scale-[0.97] " +
  "focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-[var(--blue-ring)] " +
  "disabled:opacity-50 disabled:pointer-events-none";

const btnVariants: Record<ButtonVariant, string> = {
  primary: "bg-blue text-white hover:bg-blue-strong",
  ghost: "border border-line bg-paper text-ink hover:bg-surface-2",
  quiet: "text-ink-soft hover:text-ink hover:bg-surface-2",
};

const btnSizes: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-[15px]",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(btnBase, btnVariants[variant], btnSizes[size], className)}
      {...rest}
    >
      {loading && <Spinner size={size === "sm" ? 12 : 14} />}
      {children}
    </button>
  );
});

/* ------------------------------------------------------------------ *
 * Form primitives
 * ------------------------------------------------------------------ */

const controlBase =
  "w-full rounded-lg bg-surface border border-line text-ink placeholder:text-ink-faint " +
  "transition-[border-color,box-shadow] duration-150 [transition-timing-function:var(--ease)] " +
  "focus:outline-none focus:border-blue focus:ring-[3px] focus:ring-[var(--blue-ring)] " +
  "disabled:opacity-50 disabled:pointer-events-none";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cn(controlBase, "h-10 px-3 text-sm", className)} {...rest} />;
});

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, rows = 4, ...rest },
  ref,
) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      className={cn(controlBase, "px-3 py-2 text-sm resize-y leading-relaxed", className)}
      {...rest}
    />
  );
});

export type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={cn(controlBase, "h-10 px-3 text-sm cursor-pointer", className)} {...rest}>
      {children}
    </select>
  );
});

export interface LabelProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  hint?: React.ReactNode;
}

export function Label({ className, children, hint, ...rest }: LabelProps) {
  return (
    <label className={cn("flex items-baseline justify-between gap-2 text-sm font-medium text-ink", className)} {...rest}>
      <span>{children}</span>
      {hint && <span className="text-xs font-normal text-ink-faint">{hint}</span>}
    </label>
  );
}

export interface FieldProps {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  htmlFor?: string;
  className?: string;
  children: React.ReactNode;
}

/** Label + control + optional hint/error, vertically stacked. */
export function Field({ label, hint, error, htmlFor, className, children }: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {label && (
        <Label htmlFor={htmlFor} hint={hint}>
          {label}
        </Label>
      )}
      {children}
      {error && <p className="text-xs text-bad">{error}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Surfaces
 * ------------------------------------------------------------------ */

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  as?: React.ElementType;
  padded?: boolean;
}

export function Card({ as: Tag = "div", padded = true, className, children, ...rest }: CardProps) {
  return (
    <Tag
      className={cn(
        "rounded-xl border border-line bg-surface",
        padded && "p-5",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/* ------------------------------------------------------------------ *
 * Badge / Chip / StatusDot
 * ------------------------------------------------------------------ */

const toneText: Record<Tone, string> = {
  good: "text-good",
  warn: "text-warn",
  bad: "text-bad",
  blue: "text-blue",
  neutral: "text-ink-soft",
};

const toneSoftBg: Record<Tone, string> = {
  good: "bg-[color-mix(in_oklch,var(--good)_14%,var(--paper))] text-good",
  warn: "bg-[color-mix(in_oklch,var(--warn)_16%,var(--paper))] text-[color-mix(in_oklch,var(--warn)_65%,var(--ink))]",
  bad: "bg-[color-mix(in_oklch,var(--bad)_12%,var(--paper))] text-bad",
  blue: "bg-blue-soft text-blue",
  neutral: "bg-surface-2 text-ink-soft",
};

const toneDot: Record<Tone, string> = {
  good: "bg-good",
  warn: "bg-warn",
  bad: "bg-bad",
  blue: "bg-blue",
  neutral: "bg-[var(--ink-faint)]",
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  mono?: boolean;
}

export function Badge({ tone = "neutral", mono = false, className, children, ...rest }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
        mono && "font-mono tabular-nums",
        toneSoftBg[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}

export interface ChipProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  active?: boolean;
}

/** Small outlined pill, used for skills / ATS keywords / filters. */
export function Chip({ tone = "neutral", active = false, className, children, ...rest }: ChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs",
        active
          ? "border-blue bg-blue-soft text-blue"
          : cn("border-line bg-paper", toneText[tone]),
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}

export interface StatusDotProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  pulse?: boolean;
}

export function StatusDot({ tone = "neutral", pulse = false, className, ...rest }: StatusDotProps) {
  return (
    <span
      className={cn(
        "inline-block size-2 rounded-full shrink-0",
        toneDot[tone],
        pulse && "animate-pulse",
        className,
      )}
      {...rest}
    />
  );
}

/* ------------------------------------------------------------------ *
 * Meter (0-100 bar)
 * ------------------------------------------------------------------ */

export interface MeterProps {
  value: number;
  max?: number;
  tone?: Tone;
  showValue?: boolean;
  label?: React.ReactNode;
  className?: string;
}

const toneBar: Record<Tone, string> = {
  good: "bg-good",
  warn: "bg-warn",
  bad: "bg-bad",
  blue: "bg-blue",
  neutral: "bg-[var(--ink-faint)]",
};

export function Meter({ value, max = 100, tone = "blue", showValue = false, label, className }: MeterProps) {
  const p = pct(value, max);
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {(label || showValue) && (
        <div className="flex items-baseline justify-between text-xs text-ink-soft">
          <span>{label}</span>
          {showValue && (
            <span className="font-mono tabular-nums text-ink">
              {Math.round(value)}
              {max !== 100 ? `/${max}` : ""}
            </span>
          )}
        </div>
      )}
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-surface-2"
        role="progressbar"
        aria-valuenow={p}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500 [transition-timing-function:var(--ease)]", toneBar[tone])}
          style={{ width: `${p}%` }}
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Spinner / Skeleton
 * ------------------------------------------------------------------ */

export interface SpinnerProps {
  size?: number;
  className?: string;
}

export function Spinner({ size = 16, className }: SpinnerProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={cn("animate-spin", className)}
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export type SkeletonProps = React.HTMLAttributes<HTMLDivElement>;

export function Skeleton({ className, ...rest }: SkeletonProps) {
  return <div className={cn("animate-pulse rounded-md bg-surface-2", className)} {...rest} />;
}

/* ------------------------------------------------------------------ *
 * EmptyState
 * ------------------------------------------------------------------ */

export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: React.ReactNode;
  hint?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, hint, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-line bg-surface/50 px-6 py-14 text-center",
        className,
      )}
    >
      {icon && (
        <div className="flex size-11 items-center justify-center rounded-full bg-blue-soft text-blue">
          {icon}
        </div>
      )}
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">{title}</p>
        {hint && <p className="mx-auto max-w-sm text-sm text-ink-faint">{hint}</p>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Inline error / Toast
 * ------------------------------------------------------------------ */

export interface ErrorInlineProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

export function ErrorInline({ className, children, ...rest }: ErrorInlineProps) {
  if (!children) return null;
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2 rounded-lg border border-[color-mix(in_oklch,var(--bad)_35%,var(--line))] bg-[color-mix(in_oklch,var(--bad)_8%,var(--paper))] px-3 py-2 text-sm text-bad",
        className,
      )}
      {...rest}
    >
      <span aria-hidden className="mt-0.5 select-none">!</span>
      <span>{children}</span>
    </div>
  );
}

export type ToastTone = Tone;

export interface ToastProps {
  tone?: ToastTone;
  children: React.ReactNode;
  onDismiss?: () => void;
  className?: string;
}

/** A single toast surface. Consumers position it (e.g. fixed bottom-right). */
export function Toast({ tone = "neutral", children, onDismiss, className }: ToastProps) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-center gap-3 rounded-lg border border-line bg-surface px-4 py-3 text-sm text-ink shadow-lg shadow-black/5",
        className,
      )}
    >
      <StatusDot tone={tone} />
      <span className="flex-1">{children}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="text-ink-faint hover:text-ink transition-colors"
          aria-label="Dismiss"
        >
          ×
        </button>
      )}
    </div>
  );
}
