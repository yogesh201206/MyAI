"""
core/model_ranker.py — Multi-factor model scoring and candidate ranking for Phase 11.

Evaluates eligible models from the active model catalog against a target task type
and estimated context demand.

Scoring dimensions (0 - 100 scale):
  - Task capability match:  0 - 40
  - Provider health:        0 - 25
  - Context window fit:     0 - 15
  - Latency performance:    0 - 10 (elevated to 20 in FAST mode)
  - Recent reliability:     0 - 10

Transparent, deterministic, and purely local.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import config
from core.provider_health import (
    get_provider_for_model,
    get_provider_record,
    get_provider_status,
    STATUS_AUTH_ERROR,
    STATUS_DEGRADED,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_RATE_LIMITED,
    STATUS_UNKNOWN,
)
from core.task_classifier import (
    TASK_AUTO,
    TASK_CHAT,
    TASK_CODING,
    TASK_FAST,
    TASK_REASONING,
    TASK_RESEARCH,
    TASK_VISION,
)


@dataclass
class ScoredModel:
    model_id: str
    provider: str
    total_score: float
    factors: Dict[str, float]
    reasons: List[str]
    context_length: Optional[int]
    status: str
    avg_latency_ms: Optional[float]


# ------------------------------------------------------------------
# FALLBACK ROUTES (Section 19 & 31)
# ------------------------------------------------------------------

FALLBACK_ROUTES = {
    TASK_CODING:    "auto/best-coding",
    TASK_FAST:      "auto/best-fast",
    TASK_REASONING: "auto/smart",
    TASK_RESEARCH:  "auto/smart",
    TASK_VISION:    "auto/smart",
    TASK_CHAT:      "auto",
    TASK_AUTO:      "auto",
}


def get_fallback_route(task_type: str) -> str:
    """Return appropriate OmniRoute auto route when catalog models cannot be routed."""
    return FALLBACK_ROUTES.get(task_type, "auto")


# ------------------------------------------------------------------
# CAPABILITY HEURISTICS
# ------------------------------------------------------------------

_CODING_PREFERRED_SUBSTRINGS = [
    "coder", "code", "qwen2.5-coder", "starcoder", "deepseek-coder",
    "codellama", "wizardcoder", "claude-3-5-sonnet", "gpt-4o", "gemini-1.5-pro",
]

_REASONING_PREFERRED_SUBSTRINGS = [
    "r1", "o1", "o3", "thinking", "reasoning", "claude-3-5-sonnet",
    "gemini-1.5-pro", "deepseek-r1", "qwq", "deepseek-reasoner",
]

_FAST_PREFERRED_SUBSTRINGS = [
    "flash", "mini", "haiku", "8b", "instant", "small", "groq", "turbo", "lite",
]


def _has_vision_capability(meta: dict) -> bool:
    """Return True if model metadata or ID indicates vision capability."""
    caps = meta.get("capabilities", {})
    if isinstance(caps, dict) and (caps.get("vision") or "vision" in caps):
        return True
    if isinstance(caps, (list, tuple)) and "vision" in caps:
        return True
    mid = meta.get("id", "").lower()
    return "vision" in mid or "gpt-4o" in mid or "gemini" in mid or "claude-3" in mid


def _has_reasoning_capability(meta: dict) -> bool:
    caps = meta.get("capabilities", {})
    if isinstance(caps, dict) and (caps.get("reasoning") or caps.get("thinking")):
        return True
    if isinstance(caps, (list, tuple)) and any(c in caps for c in ("reasoning", "thinking")):
        return True
    mid = meta.get("id", "").lower()
    return any(sub in mid for sub in _REASONING_PREFERRED_SUBSTRINGS)


def _has_coding_capability(meta: dict) -> bool:
    caps = meta.get("capabilities", {})
    if isinstance(caps, dict) and (caps.get("tool_calling") or caps.get("code")):
        return True
    mid = meta.get("id", "").lower()
    return any(sub in mid for sub in _CODING_PREFERRED_SUBSTRINGS)


# ------------------------------------------------------------------
# FACTOR SCORING
# ------------------------------------------------------------------

def _score_capability(meta: dict, task_type: str) -> Tuple[float, str]:
    """Score model capability match for task (0 - 40 points)."""
    mid = meta.get("id", "").lower()
    reasons = []

    if task_type == TASK_VISION:
        if _has_vision_capability(meta):
            return 40.0, "has vision capability"
        return 0.0, "lacks vision capability"

    if task_type == TASK_CODING:
        if any(sub in mid for sub in ("coder", "code", "qwen2.5-coder", "deepseek-coder")):
            return 40.0, "specialized coding model"
        if any(sub in mid for sub in ("claude-3-5-sonnet", "gpt-4o", "gemini-1.5-pro")):
            return 36.0, "high-tier coding capable model"
        if _has_coding_capability(meta):
            return 32.0, "code/tool calling capability"
        return 22.0, "general model"

    if task_type == TASK_REASONING:
        if any(sub in mid for sub in ("r1", "o1", "o3", "thinking", "reasoner", "qwq")):
            return 40.0, "specialized reasoning/thinking model"
        if any(sub in mid for sub in ("claude-3-5-sonnet", "gemini-1.5-pro", "gpt-4o")):
            return 36.0, "frontier reasoning model"
        if _has_reasoning_capability(meta):
            return 34.0, "reasoning capability in metadata"
        return 20.0, "standard model"

    if task_type == TASK_FAST:
        if any(sub in mid for sub in ("flash", "mini", "haiku", "8b", "instant", "groq")):
            return 38.0, "lightweight fast architecture"
        return 22.0, "standard latency model"

    if task_type == TASK_RESEARCH:
        ctx = meta.get("context_length") or meta.get("max_input_tokens") or 0
        if ctx >= 128000:
            return 40.0, f"large context ({ctx//1000}K) for deep research"
        if ctx >= 32000:
            return 34.0, f"sufficient context ({ctx//1000}K) for research"
        return 25.0, "moderate context for research"

    # CHAT / default
    if any(sub in mid for sub in ("claude-3-5", "gpt-4o", "gemini-1.5", "qwen")):
        return 36.0, "natural conversational model"
    return 30.0, "standard conversational model"


def _score_provider_health(status: str) -> Tuple[float, str]:
    """Score provider health (0 - 25 points)."""
    if status == STATUS_ONLINE:
        return 25.0, "provider healthy (ONLINE)"
    if status == STATUS_UNKNOWN:
        return 16.0, "provider untested (UNKNOWN)"
    if status == STATUS_DEGRADED:
        return 8.0, "provider experiencing errors (DEGRADED)"
    if status == STATUS_RATE_LIMITED:
        return 2.0, "provider rate-limited"
    return 0.0, f"provider unusable ({status})"


def _score_context_fit(meta: dict, req_tokens: int) -> Tuple[float, str]:
    """Score context window fit (0 - 15 points)."""
    ctx_limit = meta.get("context_length") or meta.get("max_input_tokens")
    if not ctx_limit:
        return 10.0, "context limit unspecified (neutral)"

    if ctx_limit < req_tokens:
        return -1.0, f"insufficient context ({ctx_limit} < {req_tokens})"

    ratio = ctx_limit / max(1, req_tokens)
    if ratio >= 8.0:
        return 15.0, f"ample context headroom ({ctx_limit//1000}K)"
    if ratio >= 4.0:
        return 13.0, f"good context headroom ({ctx_limit//1000}K)"
    if ratio >= 2.0:
        return 10.0, f"adequate context ({ctx_limit//1000}K)"
    return 6.0, f"tight context fit ({ctx_limit} vs {req_tokens} needed)"


def _score_latency(record: Optional[dict], task_type: str) -> Tuple[float, str]:
    """Score latency performance (0 - 10 points, up to 20 in FAST mode)."""
    is_fast_mode = (task_type == TASK_FAST)
    max_pts = 20.0 if is_fast_mode else 10.0

    if not record or record.get("average_latency_ms") is None:
        return (max_pts * 0.5), "no latency record (neutral)"

    lat = record["average_latency_ms"]
    if lat < 600:
        pts = max_pts
        desc = f"very fast response ({lat:.0f}ms)"
    elif lat < 1200:
        pts = max_pts * 0.8
        desc = f"fast response ({lat:.0f}ms)"
    elif lat < 2500:
        pts = max_pts * 0.6
        desc = f"acceptable latency ({lat:.0f}ms)"
    elif lat < 5000:
        pts = max_pts * 0.4
        desc = f"slower latency ({lat:.0f}ms)"
    else:
        pts = max_pts * 0.2
        desc = f"high latency ({lat:.0f}ms)"

    return pts, desc


def _score_reliability(record: Optional[dict]) -> Tuple[float, str]:
    """Score recent request reliability (0 - 10 points)."""
    if not record or (record.get("success_count", 0) == 0 and record.get("failure_count", 0) == 0):
        return 6.0, "no historical requests (neutral)"

    succ = record.get("success_count", 0)
    fail = record.get("failure_count", 0)
    total = succ + fail
    rate = succ / max(1, total)

    if rate >= 0.95:
        return 10.0, f"high success rate ({rate*100:.0f}%)"
    if rate >= 0.80:
        return 8.0, f"good success rate ({rate*100:.0f}%)"
    if rate >= 0.60:
        return 5.0, f"moderate reliability ({rate*100:.0f}%)"
    return 2.0, f"low reliability ({rate*100:.0f}%)"


# ------------------------------------------------------------------
# RANKING ENGINE
# ------------------------------------------------------------------

def rank_models(
    task_type: str,
    estimated_context_tokens: int = 1500,
    excluded_models: Optional[set] = None,
    excluded_providers: Optional[set] = None,
    weights: Optional[dict] = None,
) -> Tuple[List[ScoredModel], List[Tuple[str, str]]]:
    """
    Score and rank all eligible models in config.model_catalog.

    The FREE REGISTRY FILTER is applied BEFORE any scoring —
    paid/unknown/stale models are excluded and cannot influence results.

    Args:
        task_type: Target task (CODING, REASONING, FAST, etc.)
        estimated_context_tokens: Estimated tokens required for current turn.
        excluded_models: Set of model_ids to exclude (e.g. prior failure retry).
        excluded_providers: Set of provider names to avoid.
        weights: Optional dict with keys capability/context/health/reliability/latency
                 (Phase 14 configurable scoring). Defaults to Phase 11 fixed weights.

    Returns:
        (scored_models_sorted, rejected_candidates_with_reasons)
    """
    excluded_models = excluded_models or set()
    excluded_providers = excluded_providers or set()

    # Phase 14: configurable weights (normalised to 100-point scale)
    w = weights or {}
    w_cap  = float(w.get("capability",  0.40))
    w_ctx  = float(w.get("context",     0.20))
    w_hlth = float(w.get("health",      0.20))
    w_rel  = float(w.get("reliability", 0.15))
    w_lat  = float(w.get("latency",     0.05))
    # Normalise so they sum to 1.0
    w_sum = w_cap + w_ctx + w_hlth + w_rel + w_lat
    if w_sum <= 0:
        w_cap = 0.40; w_ctx = 0.20; w_hlth = 0.20; w_rel = 0.15; w_lat = 0.05; w_sum = 1.0
    w_cap /= w_sum; w_ctx /= w_sum; w_hlth /= w_sum; w_rel /= w_sum; w_lat /= w_sum

    # Raw max points per dimension (unchanged from Phase 11)
    MAX_CAP   = 40.0
    MAX_HLTH  = 25.0
    MAX_CTX   = 15.0
    MAX_LAT   = 20.0 if task_type == TASK_FAST else 10.0
    MAX_REL   = 10.0

    catalog = getattr(config, "model_catalog", []) or []
    if not catalog and getattr(config, "model_map", None):
        catalog = list(config.model_map.values())

    scored_list: List[ScoredModel] = []
    rejected_list: List[Tuple[str, str]] = []

    for meta in catalog:
        mid = meta.get("id")
        if not mid or mid in excluded_models:
            continue

        # Skip virtual auto aliases in direct ranking
        if mid.startswith("auto/") or mid == "auto":
            continue

        provider = get_provider_for_model(mid) or meta.get("owned_by") or "Unknown"

        # ── FREE REGISTRY GATE (MUST be first — before scoring) ──────────
        from core.free_model_registry import is_model_allowed
        if not is_model_allowed(provider, mid):
            rejected_list.append((mid, "Not verified free (blocked by AIZEN Free-Only mode)"))
            continue
        # ─────────────────────────────────────────────────────────────────

        # Hard vision filter
        if task_type == TASK_VISION and not _has_vision_capability(meta):
            rejected_list.append((mid, "Lacks vision capability"))
            continue

        # Context limit check (hard reject if context won't fit)
        ctx_pts, ctx_reason = _score_context_fit(meta, estimated_context_tokens)
        if ctx_pts < 0:
            rejected_list.append((mid, ctx_reason))
            continue

        # Provider health
        status = get_provider_status(provider)
        rec = get_provider_record(provider)

        # Avoid completely offline or auth-broken providers when they're excluded
        if status in (STATUS_AUTH_ERROR, STATUS_OFFLINE) and provider in excluded_providers:
            rejected_list.append((mid, f"Provider {provider} is {status}"))
            continue

        # Factor scores
        cap_pts,    cap_reason    = _score_capability(meta, task_type)
        health_pts, health_reason = _score_provider_health(status)
        lat_pts,    lat_reason    = _score_latency(rec, task_type)
        rel_pts,    rel_reason    = _score_reliability(rec)

        # FAST mode: speed-reweight capability
        if task_type == TASK_FAST:
            cap_pts = min(30.0, cap_pts * 0.75)

        # Apply configurable weights (scale raw pts to weighted contribution)
        weighted_cap   = cap_pts   * (w_cap  / (MAX_CAP  / 100))
        weighted_ctx   = ctx_pts   * (w_ctx  / (MAX_CTX  / 100))
        weighted_hlth  = health_pts * (w_hlth / (MAX_HLTH / 100))
        weighted_rel   = rel_pts   * (w_rel  / (MAX_REL  / 100))
        weighted_lat   = lat_pts   * (w_lat  / (MAX_LAT  / 100))

        # Penalties for degraded/excluded providers
        penalty = 0.0
        if provider in excluded_providers:
            penalty += 30.0
        if status == STATUS_RATE_LIMITED:
            penalty += 20.0
        elif status == STATUS_DEGRADED:
            penalty += 10.0

        # Use raw sum for backward compatibility with existing scoring range
        total = max(0.0, cap_pts + health_pts + ctx_pts + lat_pts + rel_pts - penalty)

        factors = {
            "capability":  round(cap_pts, 1),
            "health":      round(health_pts, 1),
            "context":     round(ctx_pts, 1),
            "latency":     round(lat_pts, 1),
            "reliability": round(rel_pts, 1),
            "total":       round(total, 1),
        }

        reasons = [cap_reason, health_reason, ctx_reason]
        if lat_pts > 5:
            reasons.append(lat_reason)

        avg_lat = rec.get("average_latency_ms") if rec else None

        scored_list.append(
            ScoredModel(
                model_id=mid,
                provider=provider,
                total_score=total,
                factors=factors,
                reasons=reasons,
                context_length=meta.get("context_length"),
                status=status,
                avg_latency_ms=avg_lat,
            )
        )

    # Sort descending by total score, then by latency ascending (lower is better)
    scored_list.sort(
        key=lambda m: (m.total_score, -(m.avg_latency_ms or 99999)),
        reverse=True,
    )

    return scored_list, rejected_list
