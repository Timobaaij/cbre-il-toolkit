"""render_measure — measure actual rendered text heights from a PNG render
of a PowerPoint slide.

The skill's predictor (`measure_text` in `build.py`) is an approximation of
how PowerPoint will render Financier Display and Calibre. It is wrong by
~10–15% on serif headlines, which compounds across stacked Flow elements
into ~0.50" of invisible dead air on long-running slides. Empirical
calibration helps but doesn't eliminate the drift.

This module is the alternative: ask PowerPoint what it actually rendered.

Workflow:

    1. Build the .pptx with python-pptx (predictor-driven, as today).
    2. Render the slide to PNG via PowerPoint COM (scripts/to_png.ps1).
    3. Construct `RenderedSlide(png_path, tone=...)`.
    4. For each text shape, call `measure_text_height(x, y, w, h)` —
       returns the actual rendered height in inches.
    5. Use the deltas (actual - predicted) to shift downstream shapes.

The slide is exported at 1600 × 900 (configured in `to_png.ps1`), and the
slide is 13.333" × 7.5", so the DPI is 1600 / 13.333 = exactly 120 DPI.
Steps 4–5 are driven by `build.resolve_slide(...)`; this module is
pure measurement and has no python-pptx dependency.

Background detection
--------------------

Text is detected as "any pixel within the declared box whose RGB differs
from the local background by more than a tolerance". The local background
is sampled from the four corners of the box (which are typically empty
of text) and the dominant corner colour is taken as the bg.

For shapes that sit on the slide background (eyebrow, title, body in
Flow), the corner samples will all be the slide tone (dark teal-green
or white). For shapes inside cards (CardFlow text), the corner samples
will be the card's fill colour. Either way, the detection works because
the corners are *outside* the text rendering and report the local bg.

Dependencies: Pillow + numpy (both standard on the build host).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np
from PIL import Image


# Standard slide / export geometry.
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5
EXPORT_PX_W = 1600
EXPORT_PX_H = 900
DEFAULT_DPI = EXPORT_PX_W / SLIDE_W_IN   # = 120.0


@dataclass
class TextBounds:
    """Result of a measurement. All values in inches, absolute slide
    coordinates. `top` / `bottom` are inclusive (first / last row with
    rendered text). `height = bottom - top + 1/dpi`."""
    top: float
    bottom: float
    height: float
    n_text_rows: int    # diagnostic: how many rows contained text


class RenderedSlide:
    """Pixel-walk measurement of a single rendered slide.

    Construct once per slide PNG; call `measure_text_height` / `measure_text_bounds`
    as many times as needed. The PNG is loaded once and held in memory as a
    numpy array for fast slicing.

    Parameters
    ----------
    png_path : Path or str
        Path to the slide PNG exported by `to_png.ps1`.
    dpi : float, optional
        Pixels per inch. Default 120.0 (matches `to_png.ps1` at 1600×900
        for a 13.333" × 7.5" slide).
    tolerance : int, optional
        Per-channel RGB tolerance for "this pixel differs from background"
        detection. Default 20 (out of 255). Lower = stricter; higher =
        more forgiving of JPEG-like compression / anti-aliasing halos.
    """

    def __init__(self, png_path: Union[Path, str], *,
                 dpi: float = DEFAULT_DPI,
                 tolerance: int = 20):
        self.path = Path(png_path)
        if not self.path.exists():
            raise FileNotFoundError(f"Slide PNG not found: {self.path}")
        img = Image.open(self.path).convert("RGB")
        self.dpi = dpi
        self.tolerance = tolerance
        self.arr = np.asarray(img, dtype=np.int16)   # (H, W, 3); int16 for diff math
        self.h_px, self.w_px = self.arr.shape[:2]

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _in_to_px(self, x: float, y: float, w: float, h: float
                  ) -> Tuple[int, int, int, int]:
        """Convert an (x, y, w, h) box in inches to (x0, y0, x1, y1) in
        pixels, clamped to image bounds."""
        x0 = max(0, int(round(x * self.dpi)))
        y0 = max(0, int(round(y * self.dpi)))
        x1 = min(self.w_px, int(round((x + w) * self.dpi)))
        y1 = min(self.h_px, int(round((y + h) * self.dpi)))
        if x1 <= x0 or y1 <= y0:
            raise ValueError(
                f"Box ({x:.3f}, {y:.3f}, {w:.3f}, {h:.3f}) inches maps to "
                f"empty pixel region ({x0},{y0})–({x1},{y1})."
            )
        return x0, y0, x1, y1

    # ------------------------------------------------------------------
    # Background sampling
    # ------------------------------------------------------------------

    def _sample_local_bg(self, crop: np.ndarray) -> np.ndarray:
        """Estimate the local background colour of a cropped region.

        Strategy: take a 5×5 patch from each of the four corners. The
        per-channel median across all 100 sample pixels is the bg.
        This is robust to a single corner happening to clip a descender
        or accent stroke, and tolerates JPEG anti-aliasing.

        Returns
        -------
        np.ndarray, shape (3,), int16
        """
        h, w = crop.shape[:2]
        patch = min(5, h // 4, w // 4) if min(h, w) >= 8 else 1
        corners = [
            crop[:patch, :patch],
            crop[:patch, -patch:],
            crop[-patch:, :patch],
            crop[-patch:, -patch:],
        ]
        all_corner_pixels = np.concatenate(
            [c.reshape(-1, 3) for c in corners], axis=0)
        return np.median(all_corner_pixels, axis=0).astype(np.int16)

    # ------------------------------------------------------------------
    # Public measurement API
    # ------------------------------------------------------------------

    def measure_text_bounds(self, x: float, y: float, w: float, h: float,
                            *, tolerance: Optional[int] = None,
                            bg: Optional[Tuple[int, int, int]] = None
                            ) -> Optional[TextBounds]:
        """Return the top/bottom y-coordinates (in inches, absolute slide
        coords) of rendered text inside the declared box. Returns None if
        no text is detected.

        Parameters
        ----------
        x, y, w, h : float
            Declared shape box in inches.
        tolerance : int, optional
            Override the instance-level tolerance for this call.
        bg : (int, int, int), optional
            Override the local-bg sample with an explicit RGB. Useful when
            you know the shape sits on a specific fill (e.g. a card's
            off-white) and want to bypass corner sampling.
        """
        tol = self.tolerance if tolerance is None else tolerance
        x0, y0, x1, y1 = self._in_to_px(x, y, w, h)
        crop = self.arr[y0:y1, x0:x1]

        bg_arr = (np.asarray(bg, dtype=np.int16) if bg is not None
                  else self._sample_local_bg(crop))

        # Per-pixel max-channel-diff from bg
        diff = np.max(np.abs(crop - bg_arr), axis=2)
        text_mask = diff > tol                          # (H, W) bool
        row_has_text = text_mask.any(axis=1)            # (H,) bool

        if not row_has_text.any():
            return None

        first_row = int(np.argmax(row_has_text))
        # last row: argmax on reversed array, then convert back
        last_row = len(row_has_text) - 1 - int(np.argmax(row_has_text[::-1]))
        n_text_rows = int(row_has_text.sum())

        top_in = (y0 + first_row) / self.dpi
        bottom_in = (y0 + last_row) / self.dpi
        height_in = bottom_in - top_in + 1.0 / self.dpi
        return TextBounds(top=top_in, bottom=bottom_in,
                          height=height_in, n_text_rows=n_text_rows)

    def measure_text_height(self, x: float, y: float, w: float, h: float,
                            **kwargs) -> float:
        """Return only the rendered text height in inches (0.0 if no text
        detected). Convenience wrapper around `measure_text_bounds`."""
        bounds = self.measure_text_bounds(x, y, w, h, **kwargs)
        return 0.0 if bounds is None else bounds.height


# ----------------------------------------------------------------------
# CLI for sanity-checking the measurement against a known PNG.
#
#   python render_measure.py <slide.png> <x> <y> <w> <h>
#
# Prints predicted_box and measured TextBounds.
# ----------------------------------------------------------------------

def _cli() -> int:
    import sys
    if len(sys.argv) < 6:
        print("usage: render_measure.py <slide.png> <x> <y> <w> <h> "
              "[--tolerance N]", file=sys.stderr)
        return 2
    png = sys.argv[1]
    x, y, w, h = (float(a) for a in sys.argv[2:6])
    tol = 20
    if "--tolerance" in sys.argv:
        tol = int(sys.argv[sys.argv.index("--tolerance") + 1])

    rs = RenderedSlide(png, tolerance=tol)
    print(f"Loaded {png}: {rs.w_px}×{rs.h_px}px at {rs.dpi:.1f} dpi")
    print(f"Querying box: x={x:.3f} y={y:.3f} w={w:.3f} h={h:.3f}\" "
          f"(tolerance={tol})")
    bounds = rs.measure_text_bounds(x, y, w, h)
    if bounds is None:
        print("  NO TEXT detected in box.")
    else:
        print(f"  top    = {bounds.top:.4f}\"")
        print(f"  bottom = {bounds.bottom:.4f}\"")
        print(f"  height = {bounds.height:.4f}\"   "
              f"(predicted h was {h:.4f}\", delta = "
              f"{bounds.height - h:+.4f}\")")
        print(f"  n_text_rows = {bounds.n_text_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
