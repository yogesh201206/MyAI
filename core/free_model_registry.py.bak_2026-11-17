"""
core/free_model_registry.py — Provider-agnostic Free-Only Model Registry for AIZEN AI.

Strict default-deny policy:
Only models explicitly registered and currently verified as absolutely free (free_verified=True, not stale)
are exposed to the user or selectable by the Smart Router.
Unknown models, paid models, trial/promotional-credit models, and stale models are hidden by default.

Key Phase 13 capabilities:
- Provider-agnostic architecture (adding future providers requires registry data/config, no code logic).
- Strict provider isolation (provider-A/model-X never authorizes provider-B/model-X).
- Staleness checking based on verified_at + configurable free_verification_days (default 30 days) and expires_at.
- Status classification: VERIFIED FREE, STALE, PAID, UNKNOWN.
- Complete Registry API: is_verified_free, get_record, get_verified_free_models, get_verified_free_models_by_provider,
  get_stale_models, get_unknown_models, get_hidden_models, verify_model, invalidate_model, refresh.
- Persistent user registry overlay in ~/.myai/free_model_registry.json.
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
import os
from typing import Dict, List, Optional, Tuple

import config


# ------------------------------------------------------------------
# DATA STRUCTURES
# ------------------------------------------------------------------

@dataclass
class FreeModelRecord:
    """
    Metadata record for a model's verified free status in AIZEN.

    Attributes:
        provider: Provider name (e.g. 'groq', 'nvidia', 'google').
        model: Exact model identifier (e.g. 'groq/openai/gpt-oss-120b').
        display_name: Human-friendly name for UI displays.
        free_verified: True ONLY if access is verified completely zero-cost.
        verification_source: Provenance URL or document citation.
        verified_at: ISO date string when verification was performed (YYYY-MM-DD).
        expires_at: Optional ISO date string when verification or free access expires.
        notes: Optional rationale or notes (e.g. reason for exclusion or terms).
    """
    provider: str
    model: str
    display_name: str
    free_verified: bool
    verification_source: str
    verified_at: Optional[str]
    expires_at: Optional[str] = None
    notes: str = ""


# ------------------------------------------------------------------
# DATE & STALENESS HELPERS
# ------------------------------------------------------------------

def parse_date(d_str: Optional[str]) -> Optional[date]:
    """Parse an ISO date string (YYYY-MM-DD or full timestamp) safely into a date object."""
    if not d_str:
        return None
    cleaned = str(d_str).strip()
    if not cleaned:
        return None
    try:
        # Try full ISO timestamp first
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
    except Exception:
        pass
    try:
        # Fallback to plain date YYYY-MM-DD
        return datetime.strptime(cleaned[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def is_record_stale(
    record: FreeModelRecord,
    as_of: Optional[date] = None,
    verification_days: Optional[int] = None,
) -> bool:
    """
    Determine whether a free model record has become stale.

    A record is stale if:
      1. It has free_verified=True, BUT:
      2. It has an expires_at date in the past relative to as_of, OR
      3. It has no valid verified_at date, OR
      4. The delta between as_of and verified_at exceeds verification_days.

    Note: Records with free_verified=False are paid/hidden, not stale-free.
    """
    if not record.free_verified:
        return False

    if as_of is None:
        as_of = datetime.now(timezone.utc).date()

    if verification_days is None:
        verification_days = getattr(
            config,
            "free_verification_days",
            getattr(config, "DEFAULT_FREE_VERIFICATION_DAYS", 30),
        )

    # 1. Check explicit expiry date
    if record.expires_at:
        exp_date = parse_date(record.expires_at)
        if exp_date and as_of > exp_date:
            return True

    # 2. Check verified_at date
    if not record.verified_at:
        return True

    v_date = parse_date(record.verified_at)
    if not v_date:
        return True

    delta = (as_of - v_date).days
    if delta > verification_days:
        return True

    return False


# ------------------------------------------------------------------
# DEFAULT REGISTRY ENTRIES
# ------------------------------------------------------------------

# Initial registry based on strict verification criteria:
# Genuine zero-cost access -> free_verified=True
# Trial credits / promotional / pay-as-you-go metered -> free_verified=False
_INITIAL_REGISTRY_RECORDS: List[FreeModelRecord] = [
    # ── Groq ──────────────────────────────────────────────────────
    FreeModelRecord(
        provider="groq",
        model="groq/openai/gpt-oss-120b",
        display_name="GPT-OSS 120B",
        free_verified=True,
        verification_source="Groq Cloud API Documentation / OmniRoute Zero-Cost Pricing Schema",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Official Groq free-tier hosted model; verified $0.00/1M tokens within platform rate limits.",
    ),
    FreeModelRecord(
        provider="groq",
        model="groq/openai/gpt-oss-20b",
        display_name="GPT-OSS 20B",
        free_verified=True,
        verification_source="Groq Cloud API Documentation",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Official Groq free-tier hosted model; verified $0.00/1M tokens within platform rate limits.",
    ),

    # ── AI Horde (Community-Powered Distributed Inference) ───────────
    # Official AI Horde terms confirm perpetual keyless/anonymous zero-cost
    # access via key '0000000000'. No credit card, no subscription, no payment.
    # Note: AI Horde image models are excluded; only text generation models are admitted.
    FreeModelRecord(
        provider="aihorde",
        model="aihorde/aphrodite/TheDrummer/Cydonia-24B-v4.3",
        display_name="Cydonia 24B (AI Horde)",
        free_verified=True,
        verification_source="AI Horde Official Documentation (https://aihorde.net/faq, https://oai.aihorde.net/v1/models)",
        verified_at="2026-10-05",
        expires_at=None,
        notes="Official AI Horde community-hosted text model; keyless anonymous access at $0.00 with zero billing requirement.",
    ),
    FreeModelRecord(
        provider="aihorde",
        model="aihorde/aphrodite/TheDrummer/Skyfall-31B-v4.2",
        display_name="Skyfall 31B (AI Horde)",
        free_verified=True,
        verification_source="AI Horde Official Documentation (https://aihorde.net/faq, https://oai.aihorde.net/v1/models)",
        verified_at="2026-10-05",
        expires_at=None,
        notes="Official AI Horde community-hosted text model; keyless anonymous access at $0.00 with zero billing requirement.",
    ),
    FreeModelRecord(
        provider="aihorde",
        model="aihorde/google/gemma-4-31b",
        display_name="Gemma 4 31B (AI Horde)",
        free_verified=True,
        verification_source="AI Horde Official Documentation (https://aihorde.net/faq, https://oai.aihorde.net/v1/models)",
        verified_at="2026-10-05",
        expires_at=None,
        notes="Official AI Horde community-hosted text model; keyless anonymous access at $0.00 with zero billing requirement.",
    ),

    # ── NVIDIA NIM ────────────────────────────────────────────────
    # NVIDIA Developer accounts provide 1,000 introductory trial credits;
    # not verified as perpetually free without billing or credit expiration.
    FreeModelRecord(
        provider="nvidia",
        model="nvidia/google/gemma-4-31b-it",
        display_name="Gemma 4 31B",
        free_verified=False,
        verification_source="NVIDIA NIM / NGC Terms & Pricing",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Uses introductory promotional credits (1,000 trial credits); not verified as perpetually free.",
    ),
    FreeModelRecord(
        provider="nvidia",
        model="nvidia/nvidia/nemotron-3-super-120b-a12b",
        display_name="Nemotron 3 Super 120B A12B",
        free_verified=False,
        verification_source="NVIDIA NIM / NGC Terms & Pricing",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Credit-based trial access; not verified as perpetually free.",
    ),
    FreeModelRecord(
        provider="nvidia",
        model="nvidia/openai/gpt-oss-20b",
        display_name="GPT-OSS 20B (NVIDIA)",
        free_verified=False,
        verification_source="NVIDIA NIM / NGC Terms & Pricing",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Credit-based trial access; not verified as perpetually free.",
    ),

    # ── Google AI Studio / Gemini ─────────────────────────────────
    # Configured OmniRoute endpoint exposes metered pricing ($0.30 / $2.50 per 1M tokens);
    # therefore it is pay-as-you-go through the configured gateway.
    FreeModelRecord(
        provider="gemini",
        model="gemini/gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        free_verified=False,
        verification_source="OmniRoute /v1/models pricing ($0.30 in / $2.50 out per 1M tokens)",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Configured API endpoint charges pay-as-you-go metered rates. Not free on configured gateway.",
    ),
    FreeModelRecord(
        provider="gemini",
        model="gemini/gemini-2.5-flash-lite",
        display_name="Gemini 2.5 Flash Lite",
        free_verified=False,
        verification_source="OmniRoute /v1/models pricing ($0.10 in / $0.40 out per 1M tokens)",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Configured API endpoint charges pay-as-you-go metered rates. Not free on configured gateway.",
    ),
    FreeModelRecord(
        provider="gemini",
        model="gemini/gemini-3-flash-preview",
        display_name="Gemini 3 Flash Preview",
        free_verified=False,
        verification_source="Google Terms / Gateway Unverified Pricing",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Unverified pricing on gateway. Blocked under default-deny.",
    ),
    FreeModelRecord(
        provider="gemini",
        model="gemini/gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash Lite",
        free_verified=False,
        verification_source="OmniRoute pricing ($0.05 in / $0.20 out per 1M tokens)",
        verified_at="2026-10-05",
        expires_at=None,
        notes="Configured API endpoint charges pay-as-you-go metered rates. Not free on configured gateway.",
    ),

    # ── Kiro ──────────────────────────────────────────────────────
    # Configured Kiro models have commercial pay-as-you-go rates attached.
    FreeModelRecord(
        provider="kiro",
        model="kiro/claude-sonnet-4.5",
        display_name="Claude Sonnet 4.5 (Kiro)",
        free_verified=False,
        verification_source="OmniRoute pricing ($3.00 in / $15.00 out per 1M tokens)",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Commercial pay-as-you-go model. Paid model.",
    ),
    FreeModelRecord(
        provider="kiro",
        model="kiro/claude-sonnet-5",
        display_name="Claude Sonnet 5 (Kiro)",
        free_verified=False,
        verification_source="OmniRoute pricing ($3.00 in / $15.00 out per 1M tokens)",
        verified_at="2026-10-05",
        expires_at=None,
        notes="Commercial pay-as-you-go model. Paid model.",
    ),
    FreeModelRecord(
        provider="kiro",
        model="kiro/deepseek-3.2",
        display_name="DeepSeek V3.2 (Kiro)",
        free_verified=False,
        verification_source="OmniRoute pricing ($0.27 in / $1.10 out per 1M tokens)",
        verified_at="2026-10-03",
        expires_at=None,
        notes="Commercial pay-as-you-go model. Paid model.",
    ),

    # ── Devin CLI Agentic ─────────────────────────────────────────
    # Commercial pay-as-you-go pricing on gateway.
    FreeModelRecord(
        provider="devin-cli-agentic",
        model="devin-cli-agentic/dva/claude-fable-5-1-max",
        display_name="Claude Fable 5.1 Max",
        free_verified=False,
        verification_source="OmniRoute pricing ($10.00 in / $50.00 out per 1M tokens)",
        verified_at="2026-10-05",
        expires_at=None,
        notes="Commercial pay-as-you-go model ($10/$50 per 1M tokens). Paid model.",
    ),
]


# ------------------------------------------------------------------
# REGISTRY CLASS
# ------------------------------------------------------------------

class FreeModelRegistry:
    """
    Provider-agnostic registry managing verified-free model definitions.

    Enforces strict default-deny:
      UNKNOWN -> Blocked
      PAID -> Blocked
      STALE -> Blocked
      ONLY VERIFIED FREE -> Allowed
    """

    def __init__(self, load_defaults: bool = True, load_user_file: bool = True):
        self._records: Dict[Tuple[str, str], FreeModelRecord] = {}
        if load_defaults:
            for rec in _INITIAL_REGISTRY_RECORDS:
                self.register(rec)
        if load_user_file:
            self.load_custom_records()

    def register(self, record: FreeModelRecord) -> None:
        """Register or update a model record."""
        norm_prov = self.normalize_provider(record.provider)
        norm_model = self.normalize_model_id(record.model).lower()
        self._records[(norm_prov, norm_model)] = record

    def unregister(self, provider: str, model: str) -> bool:
        """Remove a model record by provider and model ID."""
        norm_prov = self.normalize_provider(provider)
        norm_model = self.normalize_model_id(model).lower()
        return self._records.pop((norm_prov, norm_model), None) is not None

    def clear(self) -> None:
        """Clear all registry records (useful for testing)."""
        self._records.clear()

    def reset_defaults(self) -> None:
        """Reset registry to initial default records."""
        self._records.clear()
        for rec in _INITIAL_REGISTRY_RECORDS:
            self.register(rec)

    @staticmethod
    def normalize_provider(provider: Optional[str]) -> str:
        """
        Normalize a provider string safely.
        Trims whitespace, lowercases, and maps common alias variations.
        Does NOT alter provider boundaries.
        """
        if not provider:
            return ""
        p = str(provider).strip().lower()
        if p in ("google ai studio", "google-ai-studio", "googleaistudio"):
            return "google"
        return p

    @staticmethod
    def normalize_model_id(model_id: str) -> str:
        """Normalize a model ID string safely preserving character identity."""
        if not model_id:
            return ""
        return str(model_id).strip()

    def get_record(self, provider: Optional[str], model: str) -> Optional[FreeModelRecord]:
        """
        Find the FreeModelRecord for a given provider and model ID.
        Enforces strict provider isolation:
          - If provider is supplied, it NEVER matches a record belonging to another provider.
          - If model ID has a provider prefix that conflicts with the supplied provider, returns None.
        """
        if not model:
            return None

        norm_model = self.normalize_model_id(model)
        norm_prov = self.normalize_provider(provider)

        # Provider isolation: check if model ID has a provider prefix
        if "/" in norm_model:
            prefix_prov = self.normalize_provider(norm_model.split("/")[0])
            # If both provider and prefix are present but conflict, reject immediately
            if norm_prov and prefix_prov and norm_prov != prefix_prov:
                return None
            if not norm_prov:
                norm_prov = prefix_prov

        # 1. Direct key lookups for this provider
        candidates: List[Tuple[str, str]] = []
        if norm_prov:
            candidates.append((norm_prov, norm_model.lower()))

            # If norm_model starts with provider prefix (e.g. 'groq/openai/gpt-oss-120b')
            if norm_model.lower().startswith(f"{norm_prov}/"):
                sub = norm_model[len(norm_prov) + 1:].lower()
                candidates.append((norm_prov, sub))
            else:
                # If norm_model lacks provider prefix, check with prefix
                prepended = f"{norm_prov}/{norm_model}".lower()
                candidates.append((norm_prov, prepended))

        for key in candidates:
            if key in self._records:
                return self._records[key]

        # 2. Case-insensitive suffix / prefix search within the SAME provider
        target_lower = norm_model.lower()
        for (p, m), rec in self._records.items():
            # STRICT PROVIDER ISOLATION:
            if norm_prov and p != norm_prov:
                continue
            if not norm_prov:
                # If no provider could be determined at all, only allow exact model match
                if m == target_lower:
                    return rec
            else:
                if m == target_lower or m.endswith(f"/{target_lower}") or target_lower.endswith(f"/{m}"):
                    return rec

        return None

    def get_model_status(
        self,
        provider: Optional[str],
        model: str,
        as_of: Optional[date] = None,
        verification_days: Optional[int] = None,
    ) -> str:
        """
        Evaluate and return the strict verification status for a model.

        Returns one of:
          - 'VERIFIED FREE': explicitly registered, free_verified=True, and not stale.
          - 'STALE': registered as free, but verification period or expiration date expired.
          - 'PAID': explicitly registered with free_verified=False (paid/promotional/metered).
          - 'UNKNOWN': missing registry entry or unverified.
        """
        rec = self.get_record(provider, model)
        if rec is None:
            return "UNKNOWN"
        if not rec.free_verified:
            return "PAID"
        if is_record_stale(rec, as_of=as_of, verification_days=verification_days):
            return "STALE"
        return "VERIFIED FREE"

    def is_verified_free(
        self,
        provider: Optional[str],
        model: str,
        as_of: Optional[date] = None,
        verification_days: Optional[int] = None,
    ) -> bool:
        """
        Strict default-deny check:
        Returns True ONLY if status is 'VERIFIED FREE'.
        Unknown, Paid, and Stale models return False.
        """
        if not model:
            return False
        return (
            self.get_model_status(
                provider,
                model,
                as_of=as_of,
                verification_days=verification_days,
            )
            == "VERIFIED FREE"
        )

    def get_all_records(self) -> List[FreeModelRecord]:
        """Return all records in the registry."""
        return list(self._records.values())

    def get_verified_free_models(
        self,
        as_of: Optional[date] = None,
        verification_days: Optional[int] = None,
    ) -> List[FreeModelRecord]:
        """Return only records that are currently VERIFIED FREE (non-stale)."""
        return [
            r for r in self._records.values()
            if r.free_verified and not is_record_stale(r, as_of=as_of, verification_days=verification_days)
        ]

    def get_verified_free_models_by_provider(
        self,
        provider: str,
        as_of: Optional[date] = None,
        verification_days: Optional[int] = None,
    ) -> List[FreeModelRecord]:
        """Return VERIFIED FREE records for a specific provider."""
        norm_prov = self.normalize_provider(provider)
        return [
            r for r in self.get_verified_free_models(as_of=as_of, verification_days=verification_days)
            if self.normalize_provider(r.provider) == norm_prov
        ]

    def get_stale_models(
        self,
        as_of: Optional[date] = None,
        verification_days: Optional[int] = None,
    ) -> List[FreeModelRecord]:
        """Return records registered as free whose verification has become STALE."""
        return [
            r for r in self._records.values()
            if r.free_verified and is_record_stale(r, as_of=as_of, verification_days=verification_days)
        ]

    def get_hidden_models(self, catalog: Optional[List[dict]] = None) -> List[dict]:
        """
        Return catalog models that are excluded because they are paid, promotional, or stale.
        """
        if catalog is None:
            catalog = getattr(config, "raw_model_catalog", []) or getattr(config, "model_catalog", [])

        hidden = []
        for item in catalog:
            mid = item.get("id")
            if not mid:
                continue
            prov = item.get("owned_by")
            status = self.get_model_status(prov, mid)
            if status in ("PAID", "STALE"):
                hidden.append({**item, "free_status": status})
        return hidden

    def get_unknown_models(self, catalog: Optional[List[dict]] = None) -> List[dict]:
        """
        Return catalog models that have no verification record in the registry (UNKNOWN).
        """
        if catalog is None:
            catalog = getattr(config, "raw_model_catalog", []) or getattr(config, "model_catalog", [])

        unknown = []
        for item in catalog:
            mid = item.get("id")
            if not mid:
                continue
            prov = item.get("owned_by")
            if self.get_model_status(prov, mid) == "UNKNOWN":
                unknown.append({**item, "free_status": "UNKNOWN"})
        return unknown

    def filter_models(
        self,
        catalog: List[dict],
        as_of: Optional[date] = None,
        verification_days: Optional[int] = None,
    ) -> List[dict]:
        """
        Filter an OmniRoute model catalog to ONLY models that pass the Free-Only policy.
        """
        filtered = []
        for item in catalog:
            mid = item.get("id")
            if not mid:
                continue
            prov = item.get("owned_by")
            if not prov and "/" in mid:
                prov = mid.split("/")[0]

            if self.is_verified_free(prov, mid, as_of=as_of, verification_days=verification_days):
                filtered.append(item)

        return filtered

    # ------------------------------------------------------------------
    # PERSISTENCE & MUTATION API
    # ------------------------------------------------------------------

    def load_custom_records(self, file_path: Optional[str] = None) -> int:
        """
        Load custom or overridden records from a persistent JSON file.
        Returns count of loaded records.
        """
        target = file_path or getattr(config, "FREE_REGISTRY_FILE", None)
        if not target or not os.path.exists(target):
            return 0

        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return 0

            loaded_count = 0
            for item in data:
                if isinstance(item, dict) and "provider" in item and "model" in item:
                    rec = FreeModelRecord(
                        provider=item.get("provider", ""),
                        model=item.get("model", ""),
                        display_name=item.get("display_name", item.get("model", "")),
                        free_verified=bool(item.get("free_verified", False)),
                        verification_source=item.get("verification_source", ""),
                        verified_at=item.get("verified_at"),
                        expires_at=item.get("expires_at"),
                        notes=item.get("notes", ""),
                    )
                    self.register(rec)
                    loaded_count += 1
            return loaded_count
        except Exception:
            return 0

    def save_custom_records(self, file_path: Optional[str] = None) -> bool:
        """
        Persist current registry records to a JSON file atomically.
        """
        target = file_path or getattr(config, "FREE_REGISTRY_FILE", None)
        if not target:
            return False

        try:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            records_data = [asdict(rec) for rec in self._records.values()]
            tmp_path = f"{target}.tmp.{os.getpid()}"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(records_data, f, indent=2)
            os.replace(tmp_path, target)
            return True
        except Exception:
            return False

    def verify_model(
        self,
        provider: str,
        model: str,
        display_name: Optional[str] = None,
        source: str = "User documentation / official verification",
        notes: str = "Verified free access with no payment requirement.",
        verified_at: Optional[str] = None,
        expires_at: Optional[str] = None,
        save: bool = True,
    ) -> FreeModelRecord:
        """
        Manually record verification evidence for a model.
        Does NOT make paid API requests.
        """
        if not verified_at:
            verified_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        disp = display_name or model.split("/")[-1].replace("-", " ").title()
        record = FreeModelRecord(
            provider=provider,
            model=model,
            display_name=disp,
            free_verified=True,
            verification_source=source,
            verified_at=verified_at,
            expires_at=expires_at,
            notes=notes,
        )
        self.register(record)
        if save:
            self.save_custom_records()

        # Update active model catalog
        raw_catalog = getattr(config, "raw_model_catalog", [])
        if raw_catalog:
            config.model_catalog = self.filter_models(raw_catalog)

        return record

    def invalidate_model(
        self,
        provider: str,
        model: str,
        reason: str = "Model access is paid or requires billing",
        save: bool = True,
    ) -> bool:
        """
        Mark a model as NOT verified free (paid/hidden).
        """
        rec = self.get_record(provider, model)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if rec:
            rec.free_verified = False
            rec.notes = f"{reason} (invalidated {today})"
            self.register(rec)
        else:
            rec = FreeModelRecord(
                provider=provider,
                model=model,
                display_name=model,
                free_verified=False,
                verification_source="AIZEN Invalidation",
                verified_at=today,
                expires_at=None,
                notes=reason,
            )
            self.register(rec)

        if save:
            self.save_custom_records()

        # Re-filter active catalog
        raw_catalog = getattr(config, "raw_model_catalog", [])
        if raw_catalog:
            config.model_catalog = self.filter_models(raw_catalog)

        return True

    def refresh(
        self,
        as_of: Optional[date] = None,
        verification_days: Optional[int] = None,
    ) -> dict:
        """
        Refresh registry metadata, re-evaluate staleness, and rebuild free catalog.
        DOES NOT perform paid or network-verification requests.
        Safely merges any custom records from ~/.myai/free_model_registry.json.
        """
        # Safely merge any user-defined overlay records
        self.load_custom_records()

        if as_of is None:
            as_of = datetime.now(timezone.utc).date()

        raw_catalog = getattr(config, "raw_model_catalog", [])
        if raw_catalog:
            config.model_catalog = self.filter_models(
                raw_catalog,
                as_of=as_of,
                verification_days=verification_days,
            )

        verified = self.get_verified_free_models(as_of=as_of, verification_days=verification_days)
        stale = self.get_stale_models(as_of=as_of, verification_days=verification_days)
        unknown = self.get_unknown_models(raw_catalog)
        hidden = self.get_hidden_models(raw_catalog)

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return {
            "verified_count": len(verified),
            "stale_count": len(stale),
            "unknown_count": len(unknown),
            "hidden_count": len(hidden),
            "checked_at": now_str,
            "verification_days": verification_days or getattr(config, "free_verification_days", 30),
        }


# ------------------------------------------------------------------
# GLOBAL REGISTRY SINGLETON & ACCESSORS
# ------------------------------------------------------------------

_global_registry = FreeModelRegistry(load_defaults=True, load_user_file=True)


def get_free_registry() -> FreeModelRegistry:
    """Return the global FreeModelRegistry instance."""
    return _global_registry


def get_model_status(
    provider: Optional[str],
    model: str,
    as_of: Optional[date] = None,
    verification_days: Optional[int] = None,
) -> str:
    """Return status: VERIFIED FREE, STALE, PAID, or UNKNOWN."""
    return _global_registry.get_model_status(
        provider,
        model,
        as_of=as_of,
        verification_days=verification_days,
    )


def is_model_allowed(
    provider: Optional[str],
    model: str,
    as_of: Optional[date] = None,
    verification_days: Optional[int] = None,
) -> bool:
    """
    Central model selection validation function.

    Called by:
      - /pick
      - /use
      - /model
      - keyboard shortcuts
      - configuration loading
      - smart router selection
      - fallback model selection

    Returns True ONLY if:
      1. model == 'auto' (activates free-only smart router)
      2. model is VERIFIED FREE in the registry (not stale, not paid, not unknown)
    """
    if not model:
        return False
    if model == "auto":
        return True
    return _global_registry.is_verified_free(
        provider,
        model,
        as_of=as_of,
        verification_days=verification_days,
    )


def is_verified_free(
    provider: Optional[str],
    model: str,
    as_of: Optional[date] = None,
    verification_days: Optional[int] = None,
) -> bool:
    """Check if a specific model is currently verified free."""
    return _global_registry.is_verified_free(
        provider,
        model,
        as_of=as_of,
        verification_days=verification_days,
    )


def filter_free_models(catalog: List[dict]) -> List[dict]:
    """Filter model catalog using the global registry."""
    return _global_registry.filter_models(catalog)


def register_model(record: FreeModelRecord) -> None:
    """Register a new model record in the global registry."""
    _global_registry.register(record)


def refresh_free_registry() -> dict:
    """Re-evaluate the global free model registry."""
    return _global_registry.refresh()


def get_default_free_model() -> Optional[str]:
    """Return the first available verified-free model ID, or None."""
    # Check currently loaded verified catalog
    if getattr(config, "model_catalog", None):
        for item in config.model_catalog:
            mid = item.get("id")
            if is_verified_free(item.get("owned_by"), mid):
                return mid

    # Check verified registry records
    verified = _global_registry.get_verified_free_models()
    if verified:
        return verified[0].model

    return None
