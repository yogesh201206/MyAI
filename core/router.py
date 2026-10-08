"""
core/router.py — Smart model routing orchestrator.

Phase 11: Core routing, manual override, fallback, history, explainability.
Phase 14: router_enabled flag, configurable scoring weights, max_fallback limit,
          Phase 14 task type support (via ranker_task mapping from classifier),
          free-candidate count tracking.

Architecture:
  1. If router_enabled=False → respect manual model or show inline notice
  2. If manual override → verify free, return immediately
  3. Classify task (get ranker_task for scoring dimension)
  4. Estimate context tokens
  5. rank_models(ranker_task, weights) → VERIFIED FREE candidates only
  6. Select top candidate or report no free model
  7. On failure → get_retry_model() up to max_fallbacks

The free registry is the FIRST gate inside rank_models(); it filters before
any scoring, so paid/unknown/stale models cannot influence routing.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import config
from core.model_ranker import (
    get_fallback_route,
    rank_models,
    ScoredModel,
)
from core.provider_health import get_provider_for_model
from core.task_classifier import (
    ClassificationResult,
    classify_task,
    TASK_AUTO,
    TASK_CHAT,
    TASK_CODING,
    TASK_FAST,
    TASK_REASONING,
    TASK_RESEARCH,
    TASK_VISION,
)
from core.token_manager import estimate_chat_tokens, estimate_tokens


# ------------------------------------------------------------------
# DATA MODELS
# ------------------------------------------------------------------

@dataclass
class RoutingDecision:
    task_type: str
    selected_model: str
    provider: str
    reason: str
    confidence: float
    candidate_count: int
    free_candidate_count: int = 0
    factors: Dict[str, float] = field(default_factory=dict)
    evaluated_candidates: List[dict] = field(default_factory=list)
    rejected_candidates: List[Tuple[str, str]] = field(default_factory=list)
    is_manual_override: bool = False
    fallback_used: bool = False
    router_enabled: bool = True
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))


# ------------------------------------------------------------------
# CONTEXT ESTIMATOR
# ------------------------------------------------------------------

def estimate_request_context_tokens(prompt: str, context_details: Optional[dict] = None) -> int:
    """
    Estimate total input tokens for the request including prompt,
    chat history, attachments, RAG context, and project context.
    """
    base_chat = estimate_chat_tokens()
    prompt_toks = estimate_tokens(prompt)

    att_toks = 0
    try:
        from core.file_manager import get_attached_files
        from core.chat_manager import get_current_chat
        cur = get_current_chat()
        if cur:
            for f in get_attached_files(cur):
                att_toks += estimate_tokens(f.get("content", ""))
    except Exception:
        pass

    proj_toks = 0
    if getattr(config, "project_mode", False) and getattr(config, "active_project_path", None):
        proj_toks = getattr(config, "DEFAULT_PROJECT_MAX_TOKENS", 2500)

    rag_toks = 0
    if getattr(config, "rag_enabled", False):
        rag_toks = getattr(config, "DEFAULT_RAG_MAX_TOKENS", 2500)

    term_toks = 0
    if getattr(config, "last_command_result", None):
        term_toks = 300

    total = base_chat + prompt_toks + att_toks + proj_toks + rag_toks + term_toks + 1000
    return max(1500, total)


# ------------------------------------------------------------------
# SCORING WEIGHTS HELPER
# ------------------------------------------------------------------

def _get_weights() -> dict:
    """Return current scoring weights from config (defaults if missing)."""
    return {
        "capability":  getattr(config, "router_capability_weight",  0.40),
        "context":     getattr(config, "router_context_weight",     0.20),
        "health":      getattr(config, "router_health_weight",      0.20),
        "reliability": getattr(config, "router_reliability_weight", 0.15),
        "latency":     getattr(config, "router_latency_weight",     0.05),
    }


# ------------------------------------------------------------------
# FREE CANDIDATE COUNT HELPER
# ------------------------------------------------------------------

def count_free_candidates() -> int:
    """
    Return the number of currently verified-free models in the catalog.
    Used by /router status and tests.
    """
    try:
        from core.free_model_registry import is_model_allowed
        from core.provider_health import get_provider_for_model
        catalog = getattr(config, "model_catalog", []) or []
        if not catalog and getattr(config, "model_map", None):
            catalog = list(config.model_map.values())
        count = 0
        for meta in catalog:
            mid = meta.get("id", "")
            if not mid or mid.startswith("auto/") or mid == "auto":
                continue
            provider = get_provider_for_model(mid) or meta.get("owned_by") or "Unknown"
            if is_model_allowed(provider, mid):
                count += 1
        return count
    except Exception:
        return 0


# ------------------------------------------------------------------
# ROUTER — MAIN ENTRY
# ------------------------------------------------------------------

def route(prompt: str, context_details: Optional[dict] = None) -> RoutingDecision:
    """
    Determine the optimal model for a user prompt.

    Phase 14 flow:
      1. router_enabled check
      2. manual override check (+ free-registry gate)
      3. classify task → get ranker_task
      4. estimate context tokens
      5. rank_models with free-only filter BEFORE scoring
      6. return best candidate or empty decision
    """
    context_details = context_details or {}
    router_on = getattr(config, "router_enabled", True)

    # 1. Classify task first (needed even if router is OFF, for tracking)
    classification: ClassificationResult = classify_task(prompt, context_details)
    task_type = classification.task_type
    # Phase 14: use ranker_task for scoring dimensions
    ranker_task = getattr(classification, "ranker_task", task_type)

    # 2. Manual model selection override
    is_manual = (getattr(config, "model_selection_mode", "ROUTER").lower() == "manual")
    if is_manual or not router_on:
        manual_model = config.current_model or "auto"
        provider = get_provider_for_model(manual_model) or "Manual"

        from core.free_model_registry import is_model_allowed
        if not is_model_allowed(provider, manual_model):
            decision = RoutingDecision(
                task_type=task_type,
                selected_model="",
                provider=provider,
                reason=f"Manual model '{manual_model}' is blocked by AIZEN Free-Only mode.",
                confidence=0.0,
                candidate_count=0,
                free_candidate_count=count_free_candidates(),
                factors={"total": 0.0},
                evaluated_candidates=[],
                rejected_candidates=[(manual_model, "Not verified free in Free Model Registry")],
                is_manual_override=True,
                fallback_used=False,
                router_enabled=router_on,
            )
            _record_decision(decision)
            return decision

        decision = RoutingDecision(
            task_type=task_type,
            selected_model=manual_model,
            provider=provider,
            reason=f"{'Manual' if is_manual else 'Router OFF'} — using selected model ({manual_model})",
            confidence=1.0,
            candidate_count=1,
            free_candidate_count=count_free_candidates(),
            factors={"total": 100.0},
            evaluated_candidates=[{"model": manual_model, "score": 100.0, "provider": provider}],
            rejected_candidates=[],
            is_manual_override=is_manual,
            fallback_used=False,
            router_enabled=router_on,
        )
        _record_decision(decision)
        return decision

    # 3. Router automatic selection
    est_context = estimate_request_context_tokens(prompt, context_details)
    weights = _get_weights()
    scored_candidates, rejected_candidates = rank_models(
        task_type=ranker_task,
        estimated_context_tokens=est_context,
        weights=weights,
    )

    free_count = len(scored_candidates) + sum(
        1 for _, reason in rejected_candidates
        if "free" not in reason.lower()  # only count non-free rejections as context/health rejections
    )
    # More precise: count verified-free in catalog
    free_count = count_free_candidates()

    evaluated_summaries = [
        {
            "model": c.model_id,
            "provider": c.provider,
            "score": c.total_score,
            "factors": c.factors,
            "reasons": c.reasons,
        }
        for c in scored_candidates[:5]
    ]

    if scored_candidates:
        top = scored_candidates[0]
        reason_str = f"{', '.join(top.reasons[:2])}"
        decision = RoutingDecision(
            task_type=task_type,
            selected_model=top.model_id,
            provider=top.provider,
            reason=reason_str,
            confidence=classification.confidence,
            candidate_count=len(scored_candidates),
            free_candidate_count=free_count,
            factors=top.factors,
            evaluated_candidates=evaluated_summaries,
            rejected_candidates=rejected_candidates[:5],
            is_manual_override=False,
            fallback_used=False,
            router_enabled=True,
        )
    else:
        decision = RoutingDecision(
            task_type=task_type,
            selected_model="",
            provider="None",
            reason="No verified-free model is currently available for this task. Paid/unknown models are blocked by AIZEN Free-Only mode.",
            confidence=classification.confidence,
            candidate_count=0,
            free_candidate_count=free_count,
            factors={"total": 0.0},
            evaluated_candidates=evaluated_summaries,
            rejected_candidates=rejected_candidates[:5],
            is_manual_override=False,
            fallback_used=False,
            router_enabled=True,
        )

    _record_decision(decision)
    return decision


def get_retry_model(
    failed_model: str,
    failed_provider: Optional[str] = None,
    attempt: int = 1,
) -> Optional[str]:
    """
    Select a free fallback candidate if the router-selected model fails.

    Phase 14 rules:
      - Manual override: NEVER silently switch (return None)
      - Max retries limited by config.router_max_fallbacks
      - All fallback candidates MUST be verified free
      - Never falls back to paid/unknown/stale

    Args:
        failed_model: Model ID that failed.
        failed_provider: Provider of the failed model (used for soft penalty).
        attempt: Current retry attempt number (1-based).

    Returns:
        Alternative free model ID, or None if max retries exceeded or no candidate.
    """
    if getattr(config, "model_selection_mode", "ROUTER").lower() == "manual":
        return None

    max_fallbacks = getattr(config, "router_max_fallbacks", 2)
    if attempt > max_fallbacks:
        return None

    last = getattr(config, "last_routing_decision", None)
    task_type = getattr(last, "ranker_task", TASK_AUTO) if last else TASK_AUTO
    if not task_type or task_type == last.task_type if last else True:
        # Fall back to ranker_task from classification
        task_type = last.task_type if last else TASK_AUTO

    est_context = 1500
    excluded_models = {failed_model}
    excluded_providers = {failed_provider} if failed_provider else set()

    scored, _ = rank_models(
        task_type=task_type,
        estimated_context_tokens=est_context,
        excluded_models=excluded_models,
        excluded_providers=excluded_providers,
    )

    if scored:
        return scored[0].model_id

    # Cost-safety: NEVER fall back to unverified or paid model
    return None


# ------------------------------------------------------------------
# HISTORY & EXPLANATION HELPERS
# ------------------------------------------------------------------

def _record_decision(decision: RoutingDecision):
    """Store decision in global runtime state."""
    config.last_routing_decision = decision
    if not hasattr(config, "routing_history") or config.routing_history is None:
        config.routing_history = []
    config.routing_history.append(decision)
    if len(config.routing_history) > 20:
        config.routing_history = config.routing_history[-20:]


def format_verbose_routing(decision: RoutingDecision) -> str:
    """Format compact routing decision for verbose mode."""
    lines = [
        "[dim]Routing[/dim]",
        f"  [dim]Task      [/dim] [bold cyan]{decision.task_type}[/bold cyan]",
        f"  [dim]Model     [/dim] [bold white]{decision.selected_model}[/bold white]",
        f"  [dim]Provider  [/dim] {decision.provider}",
        f"  [dim]Reason    [/dim] [dim]{decision.reason}[/dim]",
    ]
    return "\n".join(lines)


def format_routing_explanation(decision: Optional[RoutingDecision] = None) -> str:
    """Format detailed explanation of the routing decision for /router explain."""
    if decision is None:
        decision = getattr(config, "last_routing_decision", None)

    if not decision:
        return "[dim]No routing decision has been made yet in this session.[/dim]"

    lines = []
    lines.append(f"[bold]Detected Task:[/bold]       [cyan]{decision.task_type}[/cyan] (confidence: {decision.confidence:.2f})")
    lines.append(f"[bold]Selected Model:[/bold]      [green]{decision.selected_model or '[dim]None[/dim]'}[/green]")
    lines.append(f"[bold]Provider:[/bold]            {decision.provider}")
    router_str = ("[green]ROUTER AUTO[/green]" if decision.router_enabled and not decision.is_manual_override
                  else ("[yellow]MANUAL OVERRIDE[/yellow]" if decision.is_manual_override
                        else "[dim]ROUTER OFF[/dim]"))
    lines.append(f"[bold]Selection Mode:[/bold]      {router_str}")
    lines.append(f"[bold]Free Candidates:[/bold]     {decision.free_candidate_count}")
    lines.append(f"[bold]Primary Reason:[/bold]      {decision.reason}")

    if decision.factors and not decision.is_manual_override:
        lines.append("\n[bold]Scoring Factors (0-100 total):[/bold]")
        lines.append(f"  • Capability match:   {decision.factors.get('capability', 0)} / 40")
        lines.append(f"  • Provider health:    {decision.factors.get('health', 0)} / 25")
        lines.append(f"  • Context headroom:   {decision.factors.get('context', 0)} / 15")
        lines.append(f"  • Latency score:      {decision.factors.get('latency', 0)} / 10")
        lines.append(f"  • Recent reliability: {decision.factors.get('reliability', 0)} / 10")
        lines.append(f"  [bold]• Total Score:[/bold]        [bold cyan]{decision.factors.get('total', 0)} / 100[/bold cyan]")

    if decision.evaluated_candidates:
        lines.append("\n[bold]Top Candidates Evaluated:[/bold]")
        for i, c in enumerate(decision.evaluated_candidates[:4], 1):
            marker = "✓" if c["model"] == decision.selected_model else "·"
            lines.append(f"  {i}. {marker} [cyan]{c['model']}[/cyan] ({c['provider']}) — Score: {c['score']}")

    if decision.rejected_candidates:
        lines.append("\n[bold]Rejected / Filtered Candidates:[/bold]")
        for m, why in decision.rejected_candidates[:4]:
            lines.append(f"  • [dim]{m}[/dim]: {why}")

    return "\n".join(lines)
