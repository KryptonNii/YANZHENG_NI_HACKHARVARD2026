"""Science check: reproduce published clinical-trial carbon footprints (owner: A10).

Paper: Griffiths J, Fox L, Williamson PR, on behalf of the Low Carbon Clinical Trials Group. "Quantifying the
carbon footprint of clinical trials: guidance development and case studies." BMJ Open 2024;14:e075755.

    uv run --project science python -m science.reproduce      # writes science/out/results.json

Four checks per trial (CASPS, PRIMETIME):
  method     - the paper's own activity x factor, line by line, as printed (does the arithmetic reproduce?)
  corrected  - the same with the errors we found fixed (units, double count, arithmetic), each documented
  library    - the paper's activity data x TrialPilot's parameter library (seeded Monte Carlo, P10/P50/P90)
  engine     - the TrialPilot engine on a TrialDesign rebuilt from the paper (library and paper factors)
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
