# Do Apply — Design System

White and blue, black fonts. Distinctive, not generic-SaaS. All values OKLCH.

## Color tokens (define in globals.css :root)
```
--paper:      oklch(99% 0.004 250);   /* near-white, faint cool tint, never #fff */
--surface:    oklch(97.5% 0.006 250); /* panels, cards */
--surface-2:  oklch(95.5% 0.008 250); /* insets, hover */
--line:       oklch(90% 0.01 250);    /* hairline borders */
--ink:        oklch(20% 0.02 260);    /* near-black text, faint blue tint, never #000 */
--ink-soft:   oklch(42% 0.02 258);
--ink-faint:  oklch(60% 0.018 255);
--blue:       oklch(55% 0.19 255);    /* primary brand blue: confident, deep-electric */
--blue-strong:oklch(48% 0.20 256);    /* pressed / bold */
--blue-soft:  oklch(95% 0.035 252);   /* tinted blue fills, selected states */
--blue-ring:  oklch(55% 0.19 255 / 0.35);
--good:       oklch(58% 0.14 155);
--warn:       oklch(66% 0.15 75);
--bad:        oklch(56% 0.17 25);
--ease:       cubic-bezier(0.22, 1, 0.36, 1);
```
Strategy: Restrained in the dashboard (blue = primary actions, selection, focus, active nav only). Committed on the landing (blue carries the hero, key sections, and product-shot framing). Black fonts = --ink on --paper.

## Typography
Use `geist` npm package (already installable) or next/font/google. Body/UI: **Geist**. Data/labels/scores: **Geist Mono**. Do NOT use Inter, DM Sans, Space Grotesk (reflex defaults). Headlines: Geist at tight tracking, heavy weight, large fluid clamp() sizes. Scale ratio >= 1.25. Body 15-16px, line length 65-75ch.

## Layout
- Dashboard: fixed left sidebar (nav: Analyze, Builder, LinkedIn, Jobs, Companies, History; Settings + account at bottom), content area max ~1080px, generous but rhythmic spacing. Familiar, fast.
- Landing: asymmetric, long-scroll, one dominant idea per fold, staggered load reveal. Real product screenshots as imagery (the actual app UI), framed in subtle device/browser chrome. No colored-block placeholders.
- Cards only when the right affordance; never nested cards. auto-fit minmax for responsive grids.

## Components
Every interactive element has default/hover/focus-visible/active/disabled/loading. Buttons: primary (blue fill, white text), ghost (line border), quiet (text). :active scale(0.97). focus-visible: 3px --blue-ring. Inputs: --surface bg, --line border, blue border + ring on focus. Skeletons for loading, not spinners in content. Empty states teach.

## Motion
150-250ms ease on product transitions; landing may orchestrate one staggered entrance. Only transform/opacity. Respect prefers-reduced-motion. No bounce.

## Bans
No gradient text, no glassmorphism-by-default, no side-stripe borders, no em dashes in copy, no hero-metric template, no identical 3-card feature row.
