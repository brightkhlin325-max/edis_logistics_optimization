import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from risk_policy import risk_bucket_for_probability


def test_risk_buckets_use_explicit_probability_boundaries():
    assert risk_bucket_for_probability(0.0) == "Low"
    assert risk_bucket_for_probability(0.2999) == "Low"
    assert risk_bucket_for_probability(0.30) == "Medium"
    assert risk_bucket_for_probability(0.6999) == "Medium"
    assert risk_bucket_for_probability(0.70) == "High"
    assert risk_bucket_for_probability(1.0) == "High"


def test_invalid_probability_has_safe_low_label():
    assert risk_bucket_for_probability(None) == "Low"
    assert risk_bucket_for_probability("not-a-number") == "Low"
