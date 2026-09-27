"""Configurable credit economy for verified field contributions.

Values come from the ``credits:`` block of config/settings.yaml (all optional); the defaults below
apply when a key is missing. Nothing else in the code base hard-codes a credit amount, a threshold
or a reward cost, and no amount is ever accepted from a client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from db.config import REPO_ROOT

REASONS = {
    "VERIFIED": "Verified contribution.",
    "NO_GPS": "Photo does not contain valid GPS metadata.",
    "TOO_OLD": "Photo was captured more than {days} days ago.",
    "ALREADY_ANALYZED": "This water body has already been analyzed.",
    "INVALID_LOCATION": "Photo location does not correspond to a recognized water body.",
    "INVALID_IMAGE": "The uploaded image could not be validated.",
    "LOW_QUALITY": "Image quality is insufficient for verification.",
    "DUPLICATE": "This image or observation has already been submitted.",
    "UNABLE_TO_VERIFY": "We could not reliably verify this submission.",
}

REWARD_LABELS = {
    "detailed_analysis": ("Detailed water-body analysis", "Unlock the full per-indicator breakdown for one water body."),
    "historical_quality": ("Historical water-quality analysis", "Unlock the multi-month trend view for one water body."),
    "monitoring_alerts": ("Water-body monitoring / alerts", "Get alerts when a water body you follow changes."),
    "advanced_report": ("Advanced water-quality report", "Generate an exportable advanced report."),
    "partner_reward": ("Future partner reward", "Reserved for future partner redemptions."),
}


@dataclass(frozen=True)
class CreditRules:
    award_high_quality: int = 100
    award_acceptable_quality: int = 50
    max_photo_age_days: int = 7
    duplicate_distance_m: float = 25.0
    duplicate_seconds: int = 3600
    phash_max_distance: int = 6
    max_location_distance_m: float = 150.0
    assumed_utc_offset_minutes: int = 330
    future_tolerance_seconds: int = 300
    # False (current default): a photo WITHOUT GPS / capture time is still scanned and can earn credit,
    # but the location, water-body-novelty and age checks are skipped. Metadata that IS present is
    # always enforced. Set credits.require_metadata: true (or AQUASAFE_REQUIRE_METADATA=1) for the full rules.
    require_metadata: bool = False
    min_water_like: float = 0.35  # water-scene thresholds (see imagecheck._water_scene)
    max_row_std: float = 22.0
    max_upload_bytes: int = 12 * 1024 * 1024
    min_side_px: int = 480
    high_quality_score: float = 0.70
    acceptable_quality_score: float = 0.45
    rewards: dict = field(
        default_factory=lambda: {
            "detailed_analysis": {"cost": 500, "available": False},
            "historical_quality": {"cost": 1000, "available": False},
            "monitoring_alerts": {"cost": 1500, "available": False},
            "advanced_report": {"cost": 2000, "available": False},
            "partner_reward": {"cost": 5000, "available": False},
        }
    )

    def message(self, code: str) -> str:
        return REASONS[code].format(days=self.max_photo_age_days)


@lru_cache(maxsize=1)
def load_rules() -> CreditRules:
    import os

    env = os.environ.get("AQUASAFE_REQUIRE_METADATA")
    base = CreditRules(**({"require_metadata": env.strip().lower() in ("1", "true", "yes")} if env else {}))
    try:
        import yaml

        data = yaml.safe_load((REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}
        block = data.get("credits") or {}
    except Exception:
        return base
    overrides = {}
    for key in (
        "award_high_quality", "award_acceptable_quality", "max_photo_age_days", "duplicate_distance_m",
        "duplicate_seconds", "phash_max_distance", "max_location_distance_m", "assumed_utc_offset_minutes",
    ):
        if key in block:
            overrides[key] = type(getattr(base, key))(block[key])
    if "require_metadata" in block:
        overrides["require_metadata"] = bool(block["require_metadata"])
    if isinstance(block.get("rewards"), dict):
        merged = {k: dict(v) for k, v in base.rewards.items()}
        for name, cfg in block["rewards"].items():
            if name in merged and isinstance(cfg, dict):
                merged[name].update({k: cfg[k] for k in ("cost", "available") if k in cfg})
        overrides["rewards"] = merged
    if env:
        overrides["require_metadata"] = base.require_metadata  # the environment wins over the file
    return CreditRules(**{**base.__dict__, **overrides})
