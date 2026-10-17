"""One fixed sample for the baseline and every advice comparison."""

SEED = 7
DRAWS = 200
METRICS = ("cost_usd", "site_staff_hours", "duration_months")
DELTA_METHOD = (
    f"Per-draw candidate minus your current selection (the baseline), both computed with seed "
    f"{SEED} and {DRAWS} draws using common random numbers; negative values are reductions. "
    "Feasible candidates are ranked by cost_usd P50, then site_staff_hours P50 (unknown last), "
    "then id."
)


def sampling_note(scenario_draws: int) -> str:
    return (
        f"Advice computes your current selection and every candidate with seed {SEED} and "
        f"{DRAWS} draws, in one ranking stage. The formal scenario computation uses its own draw "
        f"count ({scenario_draws:,} draws), so its figures can differ from these advice estimates. "
        "Drug supply uses the engine's own draw cap, reported in warnings."
    )
