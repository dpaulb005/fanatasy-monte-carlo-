"""Manager setup: inventory + predictions the operator can correct.

ESPN sync yields a SWID GUID and a display name per member — never an email,
and often an auto-generated handle instead of a name. This module powers the
Setup page: it lists every synced manager with the app's best guesses (a
cleaned-up real name, duplicate-account merge suggestions) and applies the
operator's corrections. The only write surface in the API (ADR-011); merges
reuse the same rules as the merge_managers command.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from rest_framework.exceptions import ValidationError

from league.analytics.engine import compute_league
from league.identity import merge_error, season_overlap
from league.models import League, Manager, TeamSeason

# ESPN auto-handles look like "espnfan6721714153"; anything with a long digit
# run is not a human name.
_HANDLE_RE = re.compile(r"\d{3,}")
_WORD_SPLIT_RE = re.compile(r"[\s_.]+")


def predict_real_name(display_name: str) -> str:
    """Best-guess human name from an ESPN display name, or "" if it's a handle.

    Conservative: only 2+ all-alphabetic words qualify. Casing is fixed only
    for all-lower/all-upper words so "mccoy jones" → "Mccoy Jones" but an
    intentional "DeAndre McCoy" passes through untouched.
    """
    name = display_name.strip()
    if not name or _HANDLE_RE.search(name):
        return ""
    words = [w for w in _WORD_SPLIT_RE.split(name) if w]
    if len(words) < 2:
        return ""
    if not all(w.replace("'", "").replace("-", "").isalpha() for w in words):
        return ""
    fixed = [w.capitalize() if w == w.lower() or w == w.upper() else w for w in words]
    return " ".join(fixed)


def _best_name(manager: Manager) -> str:
    return (manager.real_name or predict_real_name(manager.display_name) or "").strip().lower()


def _merge_suggestions(managers: list[Manager]) -> dict[int, Manager]:
    """source_id -> suggested target. Same (real or predicted) name, no season
    overlap, unmerged on both sides; the account with more seasons (older id on
    ties) is canonical. Suggestions only — never auto-applied."""
    by_name: dict[str, list[Manager]] = {}
    for m in managers:
        if m.merged_into_id is not None:
            continue
        name = _best_name(m)
        if name:
            by_name.setdefault(name, []).append(m)

    suggestions: dict[int, Manager] = {}
    for group in by_name.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda m: (-m.team_seasons.count(), m.id))
        target = group[0]
        for source in group[1:]:
            if not season_overlap(source, target) and merge_error(source, target) is None:
                suggestions[source.id] = target
    return suggestions


def setup_managers() -> dict:
    """The Setup page payload: every synced manager + predictions."""
    managers = list(
        Manager.objects.prefetch_related("team_seasons__season", "merged_into").order_by("id")
    )
    seasons_by_manager: dict[int, list[dict]] = {}
    for ts in TeamSeason.objects.select_related("season").prefetch_related("managers"):
        for m in ts.managers.all():
            seasons_by_manager.setdefault(m.id, []).append(
                {"year": ts.season.year, "team": ts.team_name}
            )
    suggestions = _merge_suggestions(managers)

    rows: list[dict] = []
    for m in managers:
        seasons = sorted(seasons_by_manager.get(m.id, []), key=lambda s: s["year"])
        suggestion = suggestions.get(m.id)
        rows.append(
            {
                "id": m.id,
                "guid": m.guid,
                "display_name": m.display_name,
                "real_name": m.real_name,
                "predicted_real_name": predict_real_name(m.display_name),
                "email": m.email,
                "merged_into": (
                    {"id": m.merged_into.id, "label": m.merged_into.label}
                    if m.merged_into
                    else None
                ),
                "seasons": seasons,
                "merge_suggestion": (
                    {
                        "target": {"id": suggestion.id, "label": suggestion.label},
                        "reason": "same name, no overlapping seasons",
                    }
                    if suggestion
                    else None
                ),
            }
        )
    rows.sort(key=lambda r: (r["seasons"][0]["year"] if r["seasons"] else 9999, r["id"]))
    return {"managers": rows}


def apply_manager_setup(payload: dict) -> dict:
    """Apply operator edits: real_name / email / merged_into per manager.

    Only provided keys are touched. Merges are validated with the shared
    rules; any name or merge change triggers a synchronous analytics rebuild
    (labels are baked into computed blobs at compute time)."""
    entries = payload.get("managers")
    if not isinstance(entries, list) or not entries:
        raise ValidationError({"managers": "must be a non-empty list"})

    by_id = {m.id: m for m in Manager.objects.all()}
    updated = 0
    merges_changed = 0
    names_changed = 0

    with transaction.atomic():
        for entry in entries:
            if not isinstance(entry, dict) or "id" not in entry:
                raise ValidationError({"managers": "each entry needs an id"})
            manager = by_id.get(entry["id"])
            if manager is None:
                raise ValidationError({"managers": f"unknown manager id {entry['id']}"})

            fields: list[str] = []
            if "real_name" in entry:
                real_name = str(entry["real_name"] or "").strip()
                if real_name != manager.real_name:
                    manager.real_name = real_name
                    fields.append("real_name")
                    names_changed += 1
            if "email" in entry:
                email = str(entry["email"] or "").strip()
                if email:
                    try:
                        validate_email(email)
                    except DjangoValidationError as exc:
                        raise ValidationError(
                            {"email": f"{manager.label}: '{email}' is not a valid email"}
                        ) from exc
                if email != manager.email:
                    manager.email = email
                    fields.append("email")
            if "merged_into" in entry:
                target_id = entry["merged_into"]
                if target_id is not None:
                    target = by_id.get(target_id)
                    if target is None:
                        raise ValidationError({"merged_into": f"unknown manager id {target_id}"})
                    error = merge_error(manager, target)
                    if error:
                        raise ValidationError({"merged_into": error})
                if manager.merged_into_id != target_id:
                    manager.merged_into_id = target_id
                    fields.append("merged_into")
                    merges_changed += 1

            if fields:
                manager.save(update_fields=fields)
                updated += 1

    recomputed = False
    if merges_changed or names_changed:
        league = League.objects.order_by("id").first()
        if league is not None:
            compute_league(league.espn_league_id)
            recomputed = True

    return {
        "updated": updated,
        "merges_changed": merges_changed,
        "analytics_recomputed": recomputed,
    }
