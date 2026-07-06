"""Day-by-day scheduler for study-plan tasks.

Given a list of decomposed tasks (each carrying ``estimate_minutes`` and
``priority``), the scheduler walks days from ``start_date`` to
``deadline`` and packs tasks one by one, never exceeding
``daily_minutes`` on any single day.

Algorithm:
1. Sort tasks by ``priority`` descending (high-priority first). The
   original index is preserved so callers can map results back to the
   input order.
2. For each task, find the earliest day whose remaining budget still
   covers the task's estimate. Tasks that exceed a single day's budget
   are still placed (on the last available day) so they are never
   silently dropped — the daily total may exceed ``daily_minutes`` only
   in that single oversized-task edge case.
3. Return a list of ``{task_index, scheduled_date, estimate_minutes,
   title, course_name}`` dicts ready for ``Todo`` persistence.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def schedule_tasks(
    tasks: list[dict[str, Any]],
    start_date: date,
    deadline: date,
    daily_minutes: int,
) -> list[dict[str, Any]]:
    """Pack ``tasks`` into per-day slots between two dates.

    Args:
        tasks: Each dict must carry ``estimate_minutes`` and
            ``priority`` (higher = sooner); ``title`` and
            ``course_name`` are passed through to the output.
        start_date: First allowable scheduling day (inclusive).
        deadline: Last allowable scheduling day (inclusive).
        daily_minutes: Per-day budget in minutes.

    Returns:
        A list of scheduling dicts, each with ``task_index``,
        ``scheduled_date``, ``estimate_minutes``, ``title``,
        ``course_name``. The list is sorted by ``scheduled_date`` then
        ``task_index`` for stable output.
    """
    if not tasks:
        return []

    # Build the day list. If deadline < start_date we still keep a
    # single day so callers get a valid (if overflowed) schedule
    # instead of an empty result that would silently drop tasks.
    days: list[date] = []
    cursor = start_date
    while cursor <= deadline:
        days.append(cursor)
        cursor += timedelta(days=1)
    if not days:
        days.append(start_date)

    # Sort by priority desc; stable so equal-priority tasks keep input
    # order. Carry the original index for the result mapping.
    indexed = list(enumerate(tasks))
    indexed.sort(
        key=lambda pair: -int(pair[1].get("priority", 0) or 0)
    )

    remaining = {d: daily_minutes for d in days}
    scheduled: list[dict[str, Any]] = []

    for original_index, task in indexed:
        estimate = int(task.get("estimate_minutes", 0) or 0)

        # Pick the earliest day that still has enough budget.
        chosen: date | None = None
        for d in days:
            if remaining[d] >= estimate:
                chosen = d
                break

        # If no day has enough budget (e.g. estimate > daily_minutes or
        # the run is full), fall back to the last available day so the
        # task is still scheduled.
        if chosen is None:
            chosen = days[-1]

        remaining[chosen] -= estimate
        scheduled.append(
            {
                "task_index": original_index,
                "scheduled_date": chosen,
                "estimate_minutes": estimate,
                "title": task.get("title", ""),
                "course_name": task.get("course_name", ""),
            }
        )

    scheduled.sort(key=lambda item: (item["scheduled_date"], item["task_index"]))
    return scheduled


__all__ = ["schedule_tasks"]
