# Agent workflow

GitHub (`alinik24/job_predator`) is canonical; no permanent local checkout is expected. Use `repo-dev job_predator` or clone the current default branch, then verify origin, branch, HEAD, and working-tree state.

Run `./bootstrap.ps1`, the repository doctor, and baseline tests before bounded work. Persistent private configuration belongs under the documented external machine configuration path, not in a source-local `.env`; never print or commit its values.

After changes, run affected tests, commit, push, verify the remote commit, and run `repo-release job_predator` when inactive. Never apply destructive dependency force-upgrades blindly.
