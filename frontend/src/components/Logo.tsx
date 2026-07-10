import * as React from "react";

/**
 * Do Apply mark: a checkmark that rises into an upward arrow.
 * The check reads "done / applied"; the arrow reads "forward, upward" — the
 * momentum of a job hunt that actually moves. One glyph, both meanings.
 */
export function Logo({
  size = 28,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label="Do Apply"
      className={className}
    >
      <rect width="32" height="32" rx="8" fill="var(--blue)" />
      {/* checkmark: dip down, then rise up-right */}
      <path
        d="M8 16.4 L13.4 21.8 L24 9.4"
        stroke="white"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* arrowhead at the tip: turns the rising stroke into a forward arrow */}
      <path
        d="M18.4 9.4 L24 9.4 L24 15"
        stroke="white"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default Logo;
