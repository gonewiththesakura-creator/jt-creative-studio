# DreamAPI Native Images And Fast Preview Design

## Goal

Make JT Creator use DreamAPI's OpenAI-compatible image endpoint as a normal image API, with reliable model, size, and quality control, while reducing the delay before the creation page and its selected preview become usable.

## Confirmed Cause

The current backend sends a text-model request to `/responses` and asks `gpt-5.6-luna` to invoke an `image_generation` tool. This introduces an avoidable routing decision: DreamAPI may return a successful text response without an image tool result, or its upstream bridge may fail with HTTP 502. That is why identical-looking attempts can work temporarily and then fail.

The current generated HTML also embeds the complete style configuration dataset. The document is about 1.2 MB before referenced previews load, so the browser cannot parse and paint the selected preview until a large, mostly non-critical payload has arrived.

## Backend Design

The application server remains the only component that knows the DreamAPI key. Browser requests continue to use the existing authenticated `/api/generate` job API, idempotency key, concurrency controls, usage quota, audit history, and uncertainty fence.

The provider hop changes to `POST /v1/images/generations` with this direct contract:

```json
{
  "model": "gpt-image-2.5-flare",
  "prompt": "...",
  "size": "864x1536",
  "quality": "low",
  "n": 1,
  "output_format": "png"
}
```

Supported models remain `gpt-image-2`, `gpt-image-2.5-flare`, and `gpt-image-2.5-sunburst`. Each model keeps its supported quality allowlist. Ratios map directly to the existing pixel dimensions: `1:1` to `1024x1024`, `2:3` to `1024x1536`, `3:2` to `1536x1024`, `9:16` to `864x1536`, and `16:9` to `1536x864`.

The response parser accepts the OpenAI Images response shape, primarily `data[0].b64_json`, and may accept `data[0].url` only if the existing bounded downloader can retrieve it safely. Empty or malformed `data` produces a diagnostic error that records the provider HTTP status, request identifier when present, returned object shape, and provider error message without exposing credentials or raw image data.

Decoded images are inspected before transformation. When the provider already returns the requested dimensions, bytes are saved without geometric normalization. The existing contain/cover normalization runs only when the returned dimensions differ, and the job record states whether normalization occurred.

The workstation egress proxy changes from a Responses-only validator and route to a native Images validator and `/dreamapi/images/generations` route. It keeps the current single-flight lock, response-size limit, hard timeout, redirect rejection, credential isolation, and uncertainty fence.

## Frontend And Loading Design

The generated HTML contains only a small boot dataset: navigation metadata, the initially selected style, and enough information to render its first thumbnail immediately. The complete style configuration moves to a versioned JSON asset generated in the same release.

On startup the page renders its shell and selected thumbnail without waiting for the full dataset. It then fetches the JSON asset, merges the full controls, and schedules non-selected thumbnail preloading during idle time. The JSON response is immutable and cacheable by its content version. Loading failure leaves the selected style usable and shows a concise retryable status instead of a blank page.

No key, provider URL, or cross-origin request is added to browser code. All image generation remains same-origin through the application server, preventing the `origin is not allowed` and browser `Failed to fetch` failure modes seen with direct DreamAPI calls.

## Compatibility And Deployment

Existing creator request fields and job history remain backward compatible. Contract health moves to a new version that explicitly names `/v1/images/generations` and the ratio-to-size mapping. Release payload and cache manifests include the new JSON asset.

Verification is staged: unit and HTTP contract tests, script-style performance checks, local browser rendering at desktop and mobile sizes, production health checks, and exactly one authorized paid production request using Flare, low quality, 9:16. A request with an uncertain provider outcome is never retried automatically.

The paid verification must prove one submit attempt, the direct model/quality/size contract, a valid nonblank PNG, and an output aspect ratio of 9:16. Release evidence is regenerated from the committed runtime bytes instead of weakening or bypassing the existing release gate.

## Non-Goals

This change does not expose DreamAPI directly to browsers, add client-supplied API keys, implement image editing, increase batch size beyond one provider image per job, or remove safety and quota controls.
