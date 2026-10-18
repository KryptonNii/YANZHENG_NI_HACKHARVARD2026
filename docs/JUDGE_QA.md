# Judge questions

Answers refer to tested code **e5c386b**, [final execution](evidence/clean-clone-20261017T041438Z/summary.json) and the [claim ledger](EVIDENCE.md); no current-code result is inferred from historical runs.

1. **Isn't this just Evinova?** Evinova already describes multi-metric design and carbon tools; our focus is an inspectable MIT implementation linking assumptions, synthetic operations and software evidence, without a uniqueness or superiority claim. [Sources](EVIDENCE.md).

2. **Where does real data come from?** ClinicalTrials.gov supplies cached registry metadata and publications supply reference data; protocol transcription candidates need review and operations feeds are synthetic. [A4](../handoffs/A4.md).

3. **How accurate are the carbon numbers?** Engine/library P50 is **+23.38% for CASPS and +22.75% for PRIMETIME** versus published totals, with substantial module gaps; both references lie inside ranges but real-world coverage is unvalidated. [Generated output](../science/out/results.json).

4. **Would QA accept AI-generated validation documents?** The report is **awaiting QA approval** and AI text stays draft; only the responsible QA organization can assess acceptance after actual human review.

5. **What's simulated?** EDC, CTMS, IRT, travel and courier feeds and demo identities are fictional; the recording uses a real API with cached registry data rather than UI mock responses.

6. **Why should Regeneron care about carbon?** We lead with cost, site workload, timing and patient burden, then inspect carbon for the same hypothetical choices. Regeneron's starter sheets frame the bottleneck as cost, timeline and site performance, so carbon stays a secondary metric.

7. **Do P10 and P90 mean you're right most of the time?** They are quantiles conditional on input and model assumptions, without demonstrated coverage of real outcomes.

8. **Does a home visit always save money?** Home nursing and logistics can add cost, and the recorded demo avoids visit changes or procedure removal because clinical eligibility has not been established.

9. **Can an author approve their own work?** Real API/browser tests reject self-approval and exercise Reviewer then QA signatures bound to the saved record, using automated fictional identities rather than actual human approval.

10. **Are the signatures and audit trail production compliant?** They are prototype controls needing production identity, security, retention and QA assessment; hash chaining cannot prevent a privileged rewrite of the entire database.

11. **How do you know an intervention worked?** The synthetic difference-in-differences estimate reports a comparison and interval under assumptions such as parallel trends; it does not prove causation or clinical effectiveness.

12. **Does it work without the internet?** The recorded cached-data offline mode works locally after dependencies are prepared, but a physically disconnected-network rehearsal was not separately performed.

13. **Does reproducing footprints validate the whole product?** It checks the disclosed carbon paths for two reference cases; cost, workload, forecasts and clinical appropriateness need separate empirical evidence.

14. **How many defects did you catch and how fast is it?** Current execution is **819/819 passed** at `8fca2d7` with **143.3 ms** median server cold compute across seven cache-miss seeds; historical **6/6 defects at d616645** was not blind, and the earlier **308.2 ms** miss remains documented. [Scope](EVIDENCE.md).

15. **What does a real pilot need?** Permitted data, prospective accuracy/workload criteria, live extraction evaluation, human timing and independent QA are needed alongside production identity, connectors and deployment verification.
