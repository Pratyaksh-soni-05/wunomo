import type { SVGProps } from "react";

/**
 * Wunomo wordmark (full logotype)
 * Fill is inherited — set `color` on this element or an ancestor.
 * Do NOT add a hardcoded fill: the hero bands, nav and footer render this
 * at different colours and opacities from one source.
 *
 * References the <symbol id="wm"> defined once by WunomoWordmarkSymbolDef
 * (rendered in RootLayout) via <use> — every instance costs one <use>
 * element, not a fresh copy of the ~11KB path. The hero's two wordmark
 * bands alone render this six times; six inlined copies would ship the
 * same path data six times over for no visual difference.
 */
export function WunomoWordmark({ title = "Wunomo", ...props }: SVGProps<SVGSVGElement> & { title?: string }) {
  return (
    <svg viewBox="0 0 2904 308" fill="currentColor" role="img" aria-label={title} {...props}>
      <use href="#wm" />
    </svg>
  );
}

export const WORDMARK_ASPECT = 9.4286;
