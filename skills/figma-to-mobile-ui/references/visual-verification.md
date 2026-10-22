# Visual verification against the Figma screenshot

Compare the running UI with the `get_screenshot` image of the same node, fix the differences, and
repeat until only intentional deviations remain.

Contents

1. [Capture the implementation](#1-capture-the-implementation)
2. [Match the size](#2-match-the-size)
3. [Compare](#3-compare)
4. [Checklist](#4-checklist)
5. [Reporting](#5-reporting)

## 1. Capture the implementation

Use the same content as the mock (put the mock's sample data into a preview or a debug build).

```bash
# Android emulator or device (PNG at device pixel density)
adb exec-out screencap -p > impl-android.png

# iOS simulator (PNG at device pixel scale)
xcrun simctl io booted screenshot impl-ios.png
```

For a single component, a preview screenshot from the IDE works; if the project already has
screenshot tests, add the new screen or component to them instead of comparing by hand only.

Pick a simulator/emulator whose width in dp/pt matches the Figma frame (for example a 390-pt-wide
iPhone frame on a 390-pt simulator). On another width, compare the parts that should not change
(paddings, gaps, type, colours), not absolute positions.

## 2. Match the size

Device screenshots are at 2x/3x; the Figma screenshot may be at 1x or 2x. Scale one to the other
before comparing. With ImageMagick installed (optional):

```bash
magick impl-ios.png -resize 390x impl-ios-1x.png
```

## 3. Compare

- Place both images side by side (or overlay at 50% opacity) and walk the checklist below, top to
  bottom of the frame.
- An automated pixel diff (`magick compare -metric AE figma.png impl.png diff.png`) is only a hint:
  font rasterisation and anti-aliasing differ between Figma and each platform, so a non-zero diff
  is normal. Use it to find regions to inspect, not as a pass/fail gate.
- Check both light and dark mode if the design has both, and one large-font configuration.

## 4. Checklist

| Area | What to check |
|---|---|
| Layout | Order of elements, alignment, which elements fill vs hug, scroll behaviour |
| Spacing | Paddings and gaps match the spacing tokens in the token map |
| Typography | Style per text element, weight, line count and truncation |
| Colour | Each surface, text and icon uses the mapped token (check dark mode) |
| Shape | Corner radii, strokes, dividers |
| Icons/images | Correct asset, size, tint, crop |
| States | Pressed, disabled, loading, error, empty — each one rendered at least in a preview |
| Accessibility | Touch targets ≥ 48 dp / 44 pt, text readable at large font sizes, tags present |
| RTL (if supported) | Layout mirrors; directional icons mirror; numbers and logos do not |

## 5. Reporting

Record each check as **PASS**, **FAIL** or **NOT RUN (reason)**, per platform:

```
Visual comparison — NoteCard (node 12:34)
  Android (Pixel, 411 dp): PASS — matches except deviation D1
  iOS (iPhone 16, 393 pt): NOT RUN — no simulator available in this environment
  Dark mode:               PASS (Android)
  Large font (200%):       PASS (Android) — body wraps to 3 lines, card grows

Design deviations
  D1  Card title uses #1A1C20 with no variable → mapped to AppTheme.colors.onSurface
  D2  Loading state not in the design → spinner in the primary button, assumed
```
