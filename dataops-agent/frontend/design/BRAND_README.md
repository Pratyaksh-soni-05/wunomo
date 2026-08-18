# Wunomo brand assets — placement

Two consumers, one source. Copy this tree into BOTH the product repo and the
marketing-site repo. Keep them byte-identical; when the logotype changes it
changes in both or they drift.

    public/brand/                 # raw files — for download, press, email, Slack
      wunomo-wordmark.svg
      wunomo-mark.svg
      alpha-parallel.svg          # <- you still owe me this one

    components/brand/             # what the APP actually renders
      WunomoWordmark.tsx
      WunomoMark.tsx
      index.ts

    app/                          # Next.js file-based metadata — auto-wired,
      icon.svg                    #   no <link> tags needed in layout.tsx
      apple-icon.png
      favicon.ico
      opengraph-image.png         # <- generate once the hero is built

    design/brand-source/          # provenance, never imported, never shipped
      wordmark-master.png         #   the raster the vector was traced from
      mark-master.png

## Why components and not <img>

`<img src="/brand/wunomo-wordmark.svg">` renders the file in isolation. It
cannot inherit `currentColor`, so the fill stays black and CSS cannot touch it.
The hero bands alone need two different colours at two different opacities, and
the footer needs a third. So the app imports the component:

    import { WunomoWordmark } from "@/components/brand";

    <WunomoWordmark className="hero-band__glyph" />

and CSS drives it:

    .hero-band--upper { color: rgb(255 255 255 / 0.14); }
    .hero-band--lower { color: rgb(6 16 36 / 0.20); }

`public/brand/` still exists, but only for humans — someone pasting the logo
into a deck, an email signature, a press kit.

## The hero bands: one symbol, six instances

Do not render <WunomoWordmark /> three times per band. That inlines the same
~11KB path six times. Define it once as an SVG <symbol> in the page and <use>
it, or render one instance and repeat it with CSS. Six copies of the path is
~70KB of duplicated DOM for zero benefit.

## app/icon.svg is a tile, not a bare mark

The bare monogram stops reading as a "w" below about 32px — at 16 and 20 it
looks like a "u". So the favicon puts the mark in white on a Royal Blue
(#0056FF) rounded tile, which holds at 16px. Same reasoning applies to the
collapsed sidebar: tile it, or don't go below 32px.

## Rules

- Never add a hardcoded `fill` to the components.
- Never re-export the SVGs through an image optimiser; they are already tight.
- The traced wordmark is now canonical. If you'd rather it were one of the
  other five drawings, decide before the screens are built, not after.
