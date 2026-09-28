# Security policy

## Supported versions

Security fixes go into the latest release. Please update to it before reporting.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it privately instead:
**[Report a vulnerability](https://github.com/baddo-baddo/OpenShaker/security/advisories/new)**
(GitHub's private vulnerability reporting). Include the OpenShaker version, what you found and how to
reproduce it.

You can expect a first reply within a week. OpenShaker is maintained by one person, so a fix may take
longer; you will be kept up to date and credited unless you prefer not to be.

## What OpenShaker does on your PC

To help you judge a report's impact:

- It listens for game telemetry on **127.0.0.1** only (UDP 5555 for Forza, 4444 for BeamNG.drive), unless
  you set the Forza listen address to `0.0.0.0` for an Xbox or another PC. It reads Assetto Corsa EVO's
  shared memory and connects to Openplanet's Data Sender on 127.0.0.1 (TCP 28765) for Trackmania. A
  second start of the app talks to the running one over 127.0.0.1 (TCP 49731) to bring its window up.
- It sends nothing over the internet. **Send feedback** only opens the GitHub issue page in your browser.
- It installs per user, without administrator rights, into `%LOCALAPPDATA%\Programs\OpenShaker`, and
  keeps its settings in `%APPDATA%\OpenShaker`.
