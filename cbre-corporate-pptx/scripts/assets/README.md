# Logo artwork

The 2026 CBRE brand guidelines require the wordmark to be the **official logo
artwork**, never typed ("do not type the logo yourself"). `build._paint_footer`
places the artwork bottom-right on every slide.

Drop the official files here, using these exact names:

| File | Used on | Notes |
|---|---|---|
| `cbre-logo-white.emf` (or `.png`) | **dark** backgrounds | white / reverse logo |
| `cbre-logo-green.emf` (or `.png`) | **light** backgrounds | colour / positive logo (CBRE Green #003F2D) |
| `cbre-logo-black.emf` (or `.png`) | optional | black, for B&W output only |

- **EMF** (vector) renders crispest in PowerPoint and scales without blur — prefer it.
  High-resolution **transparent PNG** also works. python-pptx **cannot embed SVG** —
  convert SVG to EMF or PNG first.
- The build looks for `.emf` first, then `.png`.
- Until at least the white + green files are present, the build **falls back to a
  typed wordmark** (not brand-compliant) and prints a one-time warning.
- Clear space (≥ the logo's height, per the guidelines) is preserved by the empty
  footer band around the bottom-right placement.
