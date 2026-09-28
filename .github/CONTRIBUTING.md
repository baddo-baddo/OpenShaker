# Contributing to OpenShaker

Thanks for helping! OpenShaker is a small project maintained by one person and built with Claude, an
AI model made by Anthropic. The most valuable contributions are often not code at all.

## Tell us how it feels

OpenShaker was tuned on one rig. Reports from other shakers, amplifiers, mounts and games are how it
gets better for everyone:

- **[Hardware / feel report](https://github.com/baddo-baddo/OpenShaker/issues/new?template=hardware_feel_report.yml)** -
  what works, what feels too strong, too weak or missing ("works great" is useful too).
- **[Bug report](https://github.com/baddo-baddo/OpenShaker/issues/new?template=bug_report.yml)** -
  something doesn't work or behaves wrong.
- **[Idea](https://github.com/baddo-baddo/OpenShaker/issues/new?template=feature_request.yml)** -
  a new game, effect or improvement.
- **[Discussions](https://github.com/baddo-baddo/OpenShaker/discussions)** - questions, setups and chat.

The tray menu's **Send feedback / report a bug** opens the same page. Nothing is sent automatically.
If you attach a log from `%APPDATA%\OpenShaker\logs`, read it first: file paths in it can contain your
Windows user name.

## Working on the code

Run from source (Python 3.10 or newer; tested with 3.13):

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python openshaker\app.pyw
```

Run the tests before you send a change:

```powershell
.venv\Scripts\python -m unittest discover -s tests
```

- **Tests fake the system.** A test must never touch the real registry, running processes, audio
  devices, network ports or the user's files - use the fakes in `tests/fakes.py`.
- **Match the code around you**: naming, comment style and the plain-language docs.
- **Keep changes focused**: one fix or feature per pull request, with a test when behaviour changes.
- **Docs count**: if a change affects what users see, update the README or the guide in `docs/wiki/`.
- The installer is built with `installer\build.bat` (64-bit Python 3.13 and Inno Setup 6); see
  [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md) for how the code fits together and
  [docs/CALIBRATION.md](../docs/CALIBRATION.md) for the tuning tools.

AI-assisted contributions are welcome - this project is one - as long as you have read, run and
tested what you submit, and say so in the pull request.

## Licence

By contributing you agree that your contribution is released under the project's
[MIT License](../LICENSE).
