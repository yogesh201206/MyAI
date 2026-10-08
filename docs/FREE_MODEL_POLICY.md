# AIZEN AI — Free-Only Model Policy & Verification Registry (Phase 13)

## Overview

AIZEN AI enforces an absolute, provider-agnostic **Free-Only Model Policy**.

Under this policy, AIZEN exposes, selects, and routes to **ONLY** models that are explicitly verified as absolutely free to use through their configured provider and gateway access.

AIZEN will **NEVER** silently expose or select a model that is:
- Paid or commercial
- Billing-required or requiring credit card setup
- Pay-as-you-go metered
- Promotional-credit based (e.g. temporary introductory credits)
- Trial-credit based
- Free only temporarily or under limited promotions
- Open-source but hosted through a paid API
- Stale or expired in verification
- Unknown or uncertain

**Unknown status MUST always be treated as NOT FREE.**

The system uses `VERIFIED FREE` as the only status that permits a model into the normal AIZEN free model catalog.

---

## Core Architectural Principles

1. **Strict Default-Deny**:
   - Unknown models and unknown providers are hidden by default.
   - A model is displayed, selectable, and routable if and only if it has an explicit entry in the Free Model Registry with `free_verified = True` and current non-stale verification.
   - Never use heuristic rules (such as matching keywords like `"free"` or `"gratis"` in model names).
   - Never automatically trust newly discovered OmniRoute models.

2. **Strict Provider Isolation**:
   - Free eligibility is determined by `provider + exact model identity + current verification evidence`, NOT merely `model name`.
   - `provider-A/model-X` does **NOT** authorize `provider-B/model-X`.
   - A model free on one platform remains blocked if routed through a different provider or metered endpoint.

3. **Stale Verification Lifecycle**:
   - Verification evidence decays over time.
   - Every verified model record tracks `verified_at` and an optional `expires_at`.
   - A configurable verification window (`free_verification_days`, default 30 days) governs validity.
   - If `current_date > verified_at + free_verification_days` or `current_date > expires_at`:
     $$\text{Status} \rightarrow \text{STALE}$$
   - **STALE $\neq$ FREE.** Stale models are hidden and rejected until reverified.

4. **Zero-Cost Verification Policy**:
   - AIZEN **never** performs paid API probe requests to check if a model is free.
   - A successful API response does not prove zero-cost access.
   - Verification is based strictly on documented pricing schemas, provider terms, and official access tiers.

5. **Separation of Health and Free Eligibility**:
   - Provider health (`ONLINE`, `DEGRADED`, `RATE_LIMITED`, `OFFLINE`) and free eligibility (`VERIFIED FREE`, `STALE`, `UNKNOWN`, `PAID`) are completely orthogonal.
   - Only `VERIFIED FREE` models enter the candidate pool.
   - Provider health then determines whether that verified-free model is currently operational.

6. **Configuration Compatibility & Graceful Recovery**:
   - If `~/.myai/config.json` references a model that is no longer verified free, AIZEN does not crash, delete the config, or silently incur charges.
   - AIZEN detects the disallowed model, alerts the user, switches to another verified-free model (or `auto`), and preserves all existing chat history and configuration cleanly.

---

## Model Status Classification

Every model belongs to exactly one status:

| Status | Meaning | Permitted in Catalog? |
| :--- | :--- | :--- |
| **`VERIFIED FREE`** | Explicitly registered, verified zero-cost, within verification window. | **YES** |
| **`STALE`** | Registered as free, but verification is older than `free_verification_days` (30 days) or past `expires_at`. | **NO** |
| **`PAID`** | Explicitly registered as paid, promotional-credit, trial, or metered. | **NO** |
| **`UNKNOWN`** | Discovered or requested model with no verified registry entry. | **NO** |

---

## User Commands (`/free` Suite)

AIZEN provides a dedicated command suite to inspect, verify, and manage the Free Model Registry:

- **`/free`**: Displays the active free model catalog with summary counts (Verified Free, Hidden/Paid, Stale, Unknown) and verification policy details.
- **`/free list`**: Displays a detailed table of all currently verified-free models with Provider, Model ID, Display Name, Verified Date, and Status.
- **`/free status`**: Displays full registry health and policy metadata, including total discovered models, staleness window, last checked timestamp, and default-deny enforcement. (Never displays secrets or keys).
- **`/free verify`**: Inspects models requiring verification and explains missing evidence reasons.
  - Manual verification syntax:
    ```bash
    /free verify <provider> <model_id> <source_citation> [optional display name]
    ```
- **`/free refresh`**: Re-evaluates registry staleness and rebuilds the active free catalog without making network or paid requests.

---

## Current Status of Providers & Models

### Verified Free Models
| Provider | Model ID | Status | Verification Source | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `groq` | `groq/openai/gpt-oss-120b` | VERIFIED FREE | Groq Cloud Docs / OmniRoute Zero-Cost Schema | Verified $0.00/1M tokens within platform rate limits. |
| `groq` | `groq/openai/gpt-oss-20b` | VERIFIED FREE | Groq Cloud Docs | Verified $0.00/1M tokens within platform rate limits. |
| `aihorde` | `aihorde/aphrodite/TheDrummer/Cydonia-24B-v4.3` | VERIFIED FREE | AI Horde Docs (https://aihorde.net/faq) | Community-powered distributed inference. Anonymous API key 0000000000; zero billing. |
| `aihorde` | `aihorde/aphrodite/TheDrummer/Skyfall-31B-v4.2` | VERIFIED FREE | AI Horde Docs (https://aihorde.net/faq) | Community-powered distributed inference. Anonymous API key 0000000000; zero billing. |
| `aihorde` | `aihorde/google/gemma-4-31b` | VERIFIED FREE | AI Horde Docs (https://aihorde.net/faq) | Community-powered distributed inference. Anonymous API key 0000000000; zero billing. |

### Investigated & Intentionally Excluded Models
| Provider | Model ID | Status | Reason for Exclusion |
| :--- | :--- | :--- | :--- |
| `aihorde` | `aihorde/*` (163 image models) | UNKNOWN | Excluded from text chat: these are image diffusion models (`output_modalities: ['image']`), not text LLMs. |
| `nvidia` | `nvidia/google/gemma-4-31b-it` | PAID | Uses introductory trial credits (1,000 credits); not verified perpetual free. |
| `nvidia` | `nvidia/nvidia/nemotron-3-super-120b-a12b` | PAID | Trial-credit access; not verified perpetual free. |
| `nvidia` | `nvidia/openai/gpt-oss-20b` | PAID | Trial-credit access; provider isolation prevents inheriting Groq's free status. |
| `gemini` | `gemini/gemini-2.5-flash` | PAID | Configured endpoint charges metered rates ($0.30 in / $2.50 out per 1M tokens). |
| `gemini` | `gemini/gemini-2.5-flash-lite` | PAID | Configured endpoint charges metered rates ($0.10 in / $0.40 out per 1M tokens). |
| `gemini` | `gemini/gemini-3-flash-preview` | PAID | Unverified pricing on gateway; excluded under default-deny. |
| `gemini` | `gemini/gemini-3.1-flash-lite` | PAID | Configured endpoint charges metered rates ($0.05 in / $0.20 out per 1M tokens). |
| `kiro` | `kiro/claude-sonnet-4.5` | PAID | Commercial pay-as-you-go model ($3.00 in / $15.00 out per 1M tokens). |
| `kiro` | `kiro/claude-sonnet-5` | PAID | Commercial pay-as-you-go model ($3.00 in / $15.00 out per 1M tokens). |
| `kiro` | `kiro/deepseek-3.2` | PAID | Commercial pay-as-you-go model ($0.27 in / $1.10 out per 1M tokens). |
| `devin-cli-agentic` | `devin-cli-agentic/dva/claude-fable-5-1-max` | PAID | Commercial pay-as-you-go model ($10.00 in / $50.00 out per 1M tokens). |
| `cloudflare-playground` | `cfp/*` (20 models) | UNKNOWN | Excluded: Cloudflare free allocation has daily neuron caps with billable overage / paid plan exposure. |
| `duckduckgo-web` | `ddgw/*` (6 models) | UNKNOWN | Excluded: Unofficial consumer web scraping proxy without developer API terms or SLA. |
| `opencode` | `oc/*` (10 models) | UNKNOWN | Excluded: Requires account API key; no official terms guaranteeing perpetual zero-cost access without billing. |
| `veoaifree-web` | `veoaifree-web/*` (4 models) | UNKNOWN | Excluded: Video generation models, not text chat LLMs. |
| (Any new provider) | (Any unverified model) | UNKNOWN | Default-deny: blocked until explicit verification evidence is recorded. |

---

## Special Cases & Pricing Policies

### 1. Free Allowances with Billing Exposure (Section 8)
Services that offer "X requests/day free", "10,000 neurons/day free", or "free credits" that transition to pay-as-you-go billing upon exhaustion DO NOT meet AIZEN's "absolutely free" standard. AIZEN requires zero billing exposure so that a user cannot inadvertently incur costs.

### 2. Trial & Promotional Credits (Section 9)
Introductory credits ($5 credit, 1,000 credits, 30-day trial) are temporary allowances, not permanent zero-cost access. When promotional credits expire, calls fail or bill the user. AIZEN strictly marks these models as `free_verified = False`.

### 3. AI Horde (Section 7)
AI Horde qualifies as genuinely free because it is a community-powered cluster with official zero-cost keyless access (`0000000000`). However, models must be verified for text generation capability: AI Horde's image diffusion models are excluded from AIZEN's terminal chat selection.

---

## Onboarding Future Providers & Models

Adding a future provider requires **zero code changes** to AIZEN's filtering or routing algorithms:

1. **Verify Official Zero-Cost Pricing**:
   Confirm that the provider offers genuine, perpetual zero-cost access with no billing setup or metered credit exhaustion.
2. **Register the Model**:
   Using the CLI:
   ```bash
   /free verify <provider> <model_id> <source_citation> [display_name]
   ```
   Or via `core/free_model_registry.py`:
   ```python
   register_model(
       FreeModelRecord(
           provider="future-provider",
           model="future-provider/model-id",
           display_name="Future Model",
           free_verified=True,
           verification_source="https://provider.example.com/pricing",
           verified_at="2026-10-05",
           notes="Verified perpetual free tier access."
       )
   )
   ```
3. **Verify and Refresh**:
   Run `/free status` and `/free refresh` to verify eligibility.
