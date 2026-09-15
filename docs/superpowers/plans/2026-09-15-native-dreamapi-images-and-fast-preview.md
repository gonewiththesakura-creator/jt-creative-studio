# Native DreamAPI Images And Fast Preview Implementation Plan

> Execute inline with test-driven development. Preserve all existing creator authentication, job, idempotency, quota, safety, and release transaction behavior.

**Goal:** Replace the fragile Responses image-tool bridge with DreamAPI's native OpenAI-compatible Images endpoint and make the JT Creator shell plus selected preview render before the complete style dataset is downloaded.

**Architecture:** Keep browser traffic same-origin through `server.py`. Send one validated image request through the workstation egress proxy to `/v1/images/generations`, parse the Images response, and normalize geometry only on an actual mismatch. Split generated style data into a versioned immutable JSON asset loaded after a minimal boot payload.

**Tech stack:** Python standard library HTTP server and urllib, Pillow, generated vanilla HTML/CSS/JavaScript, pytest, PowerShell deployment tooling.

---

## Task 1: Lock The Native Images Contract With Failing Tests

**Files:**
- Modify: `tests/test_dreamapi_creator_backend.py`
- Modify: `tests/test_dreamapi_workstation_egress.py`
- Modify: `tests/test_dreamapi_contract_health.py`

1. Replace dispatcher-oriented assertions with a direct request contract: endpoint `/v1/images/generations`, top-level image model, prompt, exact size, quality, `n: 1`, and PNG output.
2. Add response fixtures for `data[0].b64_json`, empty `data`, provider error metadata, exact-size passthrough, and mismatch normalization.
3. Add workstation proxy tests for `/dreamapi/images/generations` and strict rejection of text model, tools, stream, unsupported dimensions, or batch counts.
4. Add contract-health assertions for version 3 and the full ratio-to-provider-size mapping.
5. Run each file separately and confirm failures reference the old Responses contract.

## Task 2: Implement The Native Provider Hop

**Files:**
- Modify: `server.py`
- Modify: `comfy_watchdog.py`

1. Replace Responses endpoint construction with native Images endpoint construction for direct and workstation-egress modes.
2. Build the minimal direct Images JSON body using the validated job settings.
3. Parse bounded JSON and `data[0].b64_json`; retain bounded URL handling only if already available and policy-compliant.
4. Record sanitized upstream request identifiers and response-shape diagnostics on failures without persisting secrets or image base64.
5. Save exact-size valid PNG results without resampling; invoke existing contain/cover normalization only for dimension mismatch, and record the normalization decision.
6. Update the workstation validator and route while preserving one-flight, hard timeout, response size, no-redirect, and uncertainty-fence behavior.
7. Run the three Task 1 test files until green, then run creator HTTP and health HTTP tests.

## Task 3: Lock The Fast Boot Contract With Failing Tests

**Files:**
- Modify: `tests/test_preview_loading_performance.py`
- Modify: `tests/test_preview_cache_http.py`
- Modify: `tests/test_preview_assets_and_unified_styles.py`
- Modify: `tests/test_navigation_performance_contract.py`

1. Assert generated HTML no longer contains the full style configuration and stays under a conservative byte budget.
2. Assert a versioned style-data JSON asset exists, is included in the release payload, and receives immutable cache headers.
3. Assert the selected preview is present in the boot payload and full data loads asynchronously after the first render.
4. Assert non-selected preview preloading starts only after full data is available and during idle time.
5. Run script-style checks directly with Python and ordinary pytest files separately; confirm expected failures.

## Task 4: Implement Lightweight First Paint

**Files:**
- Modify: `build_unified_three_styles.py`
- Modify: `server.py`
- Modify: `tools/deploy_realism_release.py`
- Generate: `static/index.html`
- Generate: `static/promptgen.html`
- Create: `static/style-configs.<content-hash>.json`

1. Generate a deterministic content-hashed JSON asset for the complete style configuration.
2. Embed only the selected/default style boot configuration and asset URL in HTML.
3. Render the shell and selected preview synchronously, fetch and merge the complete configuration, then enable all style interactions.
4. Schedule remaining preview preload only after full configuration load and idle time; expose a concise retry state if loading fails.
5. Add immutable cache handling for the hashed JSON and include it in the atomic deployment payload.
6. Rebuild generated HTML and run all Task 3 checks until green.

## Task 5: Regression, Browser, And Release Verification

**Files:**
- Modify as required by the established evidence workflow: `audit/dreamapi_migration_20260914/verification.json`
- Modify as required by the established evidence workflow: `tools/deploy_realism_release.py`

1. Run focused DreamAPI, creator UI, preview, navigation, release safety, and deployment contract tests with script-style checks separated.
2. Run the repository's complete release test entry point and resolve only regressions caused by this change.
3. Start a local server and use browser automation at desktop and mobile sizes to verify nonblank selected preview, usable controls, no overlap, and successful full-data hydration. Measure HTML bytes and first-preview timing.
4. Commit the exact runtime payload. Compute the release payload digest from that commit and update the evidence gate only from fresh verification data.
5. Execute the formal deployment transaction. Verify public health, versioned JSON cache headers, server/workstation contract match, and no uncertainty fence.
6. Submit exactly one paid production job: `gpt-image-2.5-flare`, `low`, `9:16`. Do not retry automatically if the outcome is uncertain.
7. Verify one submit attempt, direct image contract metadata, valid nonblank PNG, exact 9:16 output, and improved page transfer/preview behavior. Store sanitized evidence and re-run the release gate.

## Acceptance Criteria

- No production image request uses Luna, `tools`, or `/responses`.
- Model, quality, and dimensions are explicit top-level Images API fields.
- A valid direct Images response becomes a downloadable PNG with one provider submission.
- 9:16 uses `864x1536` upstream and is not geometrically changed when returned exactly.
- Browser never receives the DreamAPI key and never calls DreamAPI cross-origin.
- Initial HTML is materially smaller and selected preview renders without waiting for the full style dataset.
- Existing job/idempotency/quota/safety behavior and formal rollback guarantees remain green.
- One authorized production Flare low 9:16 job completes and is recorded as fresh evidence.
