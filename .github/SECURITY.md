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
- Its only internet traffic is the **update check** (from 1.0.1): about 30 seconds after it starts and then
  once a day (sooner, after 10 minutes, 1 hour and 4 hours, if the network was down, and once more before
  an update is downloaded), it asks `api.github.com` for this repository's latest release, over HTTPS, with no
  account and nothing about you or your PC beyond the request itself. **Advanced... > Check for updates** turns it
  off completely. **Send feedback** only opens the GitHub issue page in your browser.
- Nothing is downloaded until you click **Update now**, or, only if you switched on **Install updates
  automatically** (from 1.0.2; off unless you say yes), until there is no supported game running on this PC and no game data for 5 minutes
  (from 1.0.3 also: OpenShaker's window closed).
  Then it downloads only `OpenShaker-Setup-X.Y.Z.exe` from that release on GitHub (HTTPS, GitHub hosts
  only, checked on every redirect), checks its size and its SHA-256 against the ones GitHub lists for that
  file in the release, and deletes it without running it if either check fails; without a SHA-256 from
  GitHub it downloads nothing. (1.0.1 read the SHA-256 from a separate `.sha256` file instead.) The
  verified installer runs without administrator rights. The SHA-256 is GitHub's own record of the
  release file, so it protects against damaged or swapped downloads, not against a compromised GitHub
  account; the installer is not code-signed yet.
- It installs per user, without administrator rights, into `%LOCALAPPDATA%\Programs\OpenShaker`, and
  keeps its settings in `%APPDATA%\OpenShaker`.
