"""The cleaning limits an import uses (US41 #115).

The limits are edited in the admin (zones.CleaningRules, one record per
import) in the units staff think in: dollars, miles and whole minutes.
This module turns a record into the Limits the cleaning code compares
(cents, miles, seconds), and back from the names saved in the import
history (US40), so a run's page can label its rules with its own limits.
"""

from zones.importer import clean as taxi_clean
from zones.importer.rideshare import clean as rideshare_clean
from zones.models import CleaningRules, ImportRun

# Saved in ImportRun.cleaning_limits under these names (US40 used the
# names of the constants they replace; MIN_DISTANCE_MI is new in US41).
LIMIT_NAMES = {
    "MAX_FARE_CENTS": "max_fare_cents",
    "MIN_DISTANCE_MI": "min_distance_mi",
    "MAX_DISTANCE_MI": "max_distance_mi",
    "MIN_DURATION_S": "min_duration_s",
    "MAX_DURATION_S": "max_duration_s",
}
WAIT_NAMES = {
    "MIN_WAIT_S": "min_wait_s",
    "MAX_WAIT_S": "max_wait_s",
}


def _number(value):
    """A whole number as an int (100.0 -> 100), so the saved limits and
    the rule labels read as before US41."""
    value = float(value)
    return int(value) if value.is_integer() else value


def limits_from_rules(rules):
    """The Limits (taxi) or RideshareLimits for a CleaningRules record."""
    values = {
        "max_fare_cents": int(rules.max_fare * 100),
        "min_distance_mi": _number(rules.min_distance_mi),
        "max_distance_mi": _number(rules.max_distance_mi),
        "min_duration_s": rules.min_duration_min * 60,
        "max_duration_s": rules.max_duration_min * 60,
    }
    if rules.is_rideshare:
        return rideshare_clean.RideshareLimits(
            **values,
            min_wait_s=rules.min_wait_min * 60,
            max_wait_s=rules.max_wait_min * 60,
        )
    return taxi_clean.Limits(**values)


def current_limits(dataset):
    """The limits in the admin right now. An import calls this once, when
    it starts, so a change applies from the next import."""
    return limits_from_rules(CleaningRules.current(dataset))


def saved_limits(limits):
    """The editable limits by name, as saved in the import history."""
    names = dict(LIMIT_NAMES)
    if isinstance(limits, rideshare_clean.RideshareLimits):
        names.update(WAIT_NAMES)
    return {name: getattr(limits, attr) for name, attr in names.items()}


def limits_from_saved(dataset, saved):
    """The Limits saved with a run. A name the run does not have (MIN_
    DISTANCE_MI in a run from before US41) takes its starting value."""
    names = dict(LIMIT_NAMES)
    limits_class = taxi_clean.Limits
    if dataset == ImportRun.Dataset.RIDESHARE:
        names.update(WAIT_NAMES)
        limits_class = rideshare_clean.RideshareLimits
    return limits_class(
        **{attr: saved[name] for name, attr in names.items() if name in saved}
    )


def rules_for(dataset, limits):
    """(key, label) per rule for an import, with these limits."""
    if dataset == ImportRun.Dataset.RIDESHARE:
        return rideshare_clean.rules(limits)
    return taxi_clean.rules(limits)
