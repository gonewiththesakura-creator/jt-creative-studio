# Mobile Upload and Liquid Glass Implementation Plan

**Spec:** `docs/superpowers/specs/2026-09-15-mobile-upload-and-liquid-glass-design.md`

## Task 1: Reliable video media uploads

**Files:** `server.py`, `sources/video_business.js`, focused upload tests.

1. Write failing tests for raw binary upload parsing, size/type validation, and the generated page's no-Base64 contract.
2. Add a bounded private temporary-file reader and streaming RunningHub multipart sender; keep the legacy JSON path compatible.
3. Change the video client to upload `File` bodies with encoded trusted metadata, exact type/size preflight, immediate local previews, and object URL cleanup.
4. Run upload and video-workbench tests.

## Task 2: Non-modal DreamAPI popover

**Files:** `build_unified_three_styles.py`, creator UI tests.

1. Write failing contract tests for no backdrop, no side drawer, and an upward anchored popover.
2. Move the existing settings DOM into the creation footer while preserving IDs and parameter controls.
3. Implement toggle, Escape, close/focus return, and hidden/inert state without blocking the page.
4. Rebuild creator artifacts and run DreamAPI UI tests.

## Task 3: Shared liquid-glass workbench system

**Files:** `sources/workbench_glass.css`, all three builders, focused visual/layout tests.

1. Add shared neutral tokens, future background layer, restrained glass shells, edge highlights, reduced-motion and fallback rules.
2. Embed the source in all builders and include it in release/runtime ownership where required.
3. Normalize mobile footers to document flow, touch sizes, long-text wrapping, and stable media dimensions.
4. Rebuild all generated pages and run layout/visual contract tests.

## Task 4: Integration, production canary, and release

1. Run syntax checks, focused suites, then the complete release suite; update reviewed test-inventory/evidence pins only from measured values.
2. Verify desktop/mobile in a real browser with console and overlap checks.
3. Restart the exact Windows watchdog if its runtime changed.
4. Prepare a loopback-only production candidate from the final commit, submit exactly one Flare/low/9:16 request, collect and visually inspect the 864x1536 PNG, and archive sanitized evidence.
5. Update the DreamAPI evidence gate, formally deploy through `tools/deploy_realism_release.py`, and recheck public health, assets, and UI.
