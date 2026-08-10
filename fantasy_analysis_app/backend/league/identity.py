"""Manager identity-merge rules, shared by merge_managers and the setup API.

A merge is a reversible pointer (``Manager.merged_into``); analytics resolve
it at compute time (see ADR-009 and the merge_managers command docstring).
These checks keep merges one level deep and refuse merging two accounts that
fielded teams in the same season — one human cannot own two teams at once.
"""

from __future__ import annotations

from league.models import Manager


def merge_error(source: Manager, target: Manager) -> str | None:
    """Why source may not merge into target, or None if the merge is legal."""
    if source.id == target.id:
        return "Cannot merge a manager into itself."
    if target.merged_into_id is not None:
        return (
            f"Target {target.label} (id {target.id}) is itself merged into "
            f"manager {target.merged_into_id}; merge into the canonical manager "
            "instead (chains are not allowed)."
        )
    if source.merged_from.exists():
        return (
            f"Source {source.label} (id {source.id}) has managers merged into it; "
            "unmerge those first (chains are not allowed)."
        )
    overlap = season_overlap(source, target)
    if overlap:
        return (
            f"{source.label} and {target.label} both fielded teams in "
            f"{', '.join(map(str, overlap))} — one human cannot own two teams "
            "in a season, so these look like different people. Refusing to merge."
        )
    return None


def season_overlap(a: Manager, b: Manager) -> list[int]:
    return sorted(
        set(a.team_seasons.values_list("season__year", flat=True))
        & set(b.team_seasons.values_list("season__year", flat=True))
    )
