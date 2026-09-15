# Mobile Upload and Liquid Glass Design

## Goal

Make creator and video workflows reliable on phones, keep DreamAPI settings attached to the generation controls, and give all three workbenches a restrained liquid-glass shell that can later sit over a user-selected background.

## Upload Contract

- Video-workbench media uploads use `POST /api/upload` with the raw `File` as the request body.
- `workflow`, `input_key`, and `filename` are percent-encoded query parameters. The browser sends `application/octet-stream` and never creates a Base64 copy.
- The server requires a valid `Content-Length`, caps the raw body at 60 MiB, streams it into a private temporary file, validates its magic bytes and trusted workflow slot, then streams multipart data to RunningHub.
- Existing JSON uploads remain temporarily supported for old clients and tests, but the generated video page uses only the binary path.
- Accepted image types are PNG, JPEG, and WebP. Accepted video types are MP4, MOV, AVI, WebM, and MKV. The browser rejects unsupported extensions and files over 60 MiB before network work.
- A selected file immediately renders as a local image or `video controls playsinline preload=metadata`. Object URLs are revoked on replacement, workflow change, and page unload.
- Upload status is visible beside the preview. A failed upload keeps the local preview so the user can retry or replace the file.

## DreamAPI Settings

- Keep existing public element IDs and API request semantics.
- Remove the full-screen backdrop and right-side modal behavior.
- The settings panel is anchored to the generation footer and opens upward from the API settings button. It is non-modal: the rest of the page remains visible and usable.
- The trigger toggles the panel, `Escape` and the close button close it, `aria-expanded` reflects state, and hidden controls are not keyboard-focusable.
- Desktop and phone layouts keep the panel within the viewport with its own bounded scroll area.

## Visual System

- Add one shared `sources/workbench_glass.css`, embedded by the creator, realism, and video builders.
- Use glass only for navigation chrome, major workbench shells, overlays, and the API popover. Inputs and media inspection areas retain high-opacity neutral surfaces.
- Edge deformation is a static masked highlight plus a sub-pixel transform on hover/focus; blur, shadow, and large backgrounds are never continuously animated.
- Root variables include `--app-background-image`, size, position, opacity, and veil. A fixed pointer-inert background layer makes future background selection a variable update, not a layout rewrite.
- Default palette remains neutral with blue brand, green success, amber warning, and red error accents. Mobile blur is reduced and reduced-motion disables edge motion.

## Responsive Rules

- At 820 px and below, creator, realism, and video footers participate in normal document flow. No fixed footer or magic bottom padding may hide fields, status, or previews.
- Controls are at least 44 px tall on touch screens and text inputs use 16 px on phones.
- Long filenames, task names, and errors wrap without horizontal overflow.
- The preview header may wrap; media keeps an explicit aspect-ratio or stable minimum height.

## Acceptance

- Unit/contract tests cover binary upload validation and legacy compatibility.
- DOM tests cover immediate preview, URL cleanup, exact accept lists, 60 MiB rejection, and absence of Base64 conversion.
- Creator tests prove no backdrop/right drawer and verify upward popover semantics.
- Builders remain authoritative and generated artifacts are rebuilt once.
- Browser checks cover `/`, `/realism`, and `/video` at 1440x900 and 390x844 with no overlap or horizontal overflow.
- Final DreamAPI canary uses the final runtime commit and exactly one Flare/low/9:16 paid submission.
