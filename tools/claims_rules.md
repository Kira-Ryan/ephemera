# Claims rules

What `tools/claims_lint.py` enforces on the site and the outward documents. A phrase below fails the
build, and a built page that drops a required caveat fails it too.

## Prohibited wording

- "Independent check of SpaceX's manoeuvre count", "confirms", "refutes", or any ratio of a detected
  quantity to the FCC figure.
- "Covariance realism" for the overlap scoreboard.
- "Anyone can re-fetch the inputs" or "reproducible from SpaceX" for anything older than one cycle.
- "Ground truth" for operator ephemerides. They are predictions; say "operator truth" or
  "operator-published trajectory", and say once per page that it is a prediction.
- "Every manoeuvre in the catalogue", "catalogue-wide detection".
- "Audit of 18 SDS", "operator transparency index", or any per-operator grade.
- "Validated", "human-validated", "playtested" for anything not yet validated by a named external
  party.
- Any precise figure without its as-of date and measurement method.

## Required caveats (once per page, verbatim or equivalent)

- "Operator ephemerides are predictions, not observations."
- "Starlink is the only operator with public covariance; other operators enter via CelesTrak SupGP
  without covariance." (until that changes)
- "Public GP data is too noisy to test sub-metre covariance; the self-consistency scoreboard measures
  prediction-versus-later-prediction."
- "Inputs are archived by this project and witnessed by OpenTimestamps and the Wayback Machine; they
  are not re-fetchable from the source after one cycle."
- Truth-health indicator on every scored day: file count received, poller uptime, mean element age,
  Space-Track status.

## Corrections

Anything published that turns out wrong is corrected and logged in `CORRECTIONS.md`.
