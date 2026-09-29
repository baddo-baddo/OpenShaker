# Start with Windows, updates and uninstalling

[OpenShaker guide](README.md) › Using OpenShaker

How Start with Windows works, how updates install, what the uninstaller removes, and what OpenShaker tidies up after older versions.

## Start with Windows

This is a single entry named **OpenShaker** in your Windows sign-in list (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). It starts `OpenShaker.exe --hidden`, straight into the tray. You can switch it on or off with the installer option, the window checkbox or the tray menu. All three change the same entry.

## Updating

### The update check

About 30 seconds after it starts, and then once a day, OpenShaker asks GitHub whether a newer version has been released. The request carries nothing but the app's name and version, and nothing is downloaded (unless you switched on [automatic updates](#automatic-updates)). If there is a newer version:

- the tray icon gets a small red **!** in its corner;
- the tray menu starts with **Update to X.Y.Z** and **What's new**;
- the window shows a yellow bar at the top: "OpenShaker X.Y.Z is available", with **Update now**, **What's new** and **Skip this version**.

![The update bar at the top of the window: "OpenShaker 1.0.3 is available (you have 1.0.2)." with the buttons Update now, What's new and Skip this version, and under it the one-time question "Install updates automatically when no game is running?" with Yes and No (an example)](../images/update_bar.png)

There is **no pop-up or notification**: you see it when you open the window or the tray menu.

- **What's new** opens the release page with the changes in your browser.
- **Skip this version** hides the badge and the bar for that version. They come back when a newer one is released. If that newer one is withdrawn again and GitHub's latest is the version you skipped, the bar goes away.
- **Advanced... > Check for updates** switches the check off; OpenShaker then never contacts the internet. To rule out every network request on a PC for good, set the environment variable `OPENSHAKER_OFFLINE=1`.
- If the check fails, nothing is shown. After a network problem (no internet yet, for example just after the PC woke up) it tries again after 10 minutes, then 1 hour, then 4 hours; otherwise the next day. Failed checks and updates are noted in `%APPDATA%\OpenShaker\logs\update.log` (the last 50 lines).

### Update now

1. If a game is sending data, OpenShaker opens its window and asks first: "Haptics will stop for about 15 seconds while OpenShaker updates. Update now?"
2. It asks GitHub once more and installs only the version you clicked. If that release was withdrawn or replaced in the meantime, or GitHub's latest is now a version you skipped, it installs nothing, and the bar shows what is on offer now, if anything.
3. It downloads the new installer from the project's GitHub release, into a new folder under `%TEMP%`. It only downloads over HTTPS from GitHub, and gives up if the download takes far too long.
4. It checks the file's size and its SHA-256 against the ones GitHub lists for that file in the release. If anything does not match, it deletes the download, says so in the bar ("Update to X.Y.Z failed: ... Nothing was installed; Update now tries again.") and installs nothing. It checks the file once more right before running it. If GitHub lists no SHA-256 for the file, nothing is downloaded, and the bar says to get the installer from the release page (**What's new**).
5. It runs the installer silently. The installer closes OpenShaker, installs the new version over the old one (same folder, no administrator prompt) and starts OpenShaker again: with its window if you clicked **Update now** in the window, in the tray if you used the tray menu. Your settings stay as they are, and so do Start with Windows and the desktop shortcut: whatever you have now is kept.
6. If the installer stops after it closed OpenShaker, it waits up to 30 seconds for OpenShaker to be gone, then starts the installed copy again, which says in its bar what happened:
   - **"The update to X.Y.Z did not install"**: the installer stopped before it replaced any file (for example OpenShaker took too long to close). Nothing changed, and the update is offered again. After an [automatic update](#automatic-updates) the bar says instead that it will not be installed automatically again: **Update now** is still there.
   - **"The update to X.Y.Z stopped partway"**: it stopped while replacing files (for example a locked file or a full disk). The installer keeps no copy of the files it replaced, so OpenShaker may now be a mix of both versions. Run the installer from the release page (**What's new**) to repair it; if the update is offered again, **Update now** does the same.

   If OpenShaker never closed, it is still running and reports the failure itself: if the installer ends, or has not finished after about three minutes, while OpenShaker is still running, the bar says so and **Update now** can be tried again.

While an update started from the tray runs, the tray item reads **Updating to X.Y.Z...**; if it fails, it reads **Update to X.Y.Z failed - open OpenShaker**, and opening the window shows why. Every failure is also noted in `update.log`.

A copy run from source can't update itself: **Update now** opens the release page instead.

### Automatic updates

Off unless you switch them on. When an update is found, the update bar also asks **"Install updates automatically when no game is running?"** with **Yes** and **No**, until you answer it:

- **Yes** switches automatic updates on, for this update and later ones. **No** leaves them off.
- Clicking **Update now** or **Skip this version** instead counts as an answer too, so the question does not come back.
- You can change your mind any time under **Advanced... > Install updates automatically**.
- It is a line in the bar, never a pop-up or a notification.

When they are on and an update is found:

1. OpenShaker waits for a quiet moment: no supported game running on this PC, no game data for 5 minutes (also counted from when OpenShaker started), and OpenShaker's own window closed, with no test tone playing. It looks again every 30 seconds, so an update never starts in the middle of a drive, or while you are using OpenShaker.
2. It then does exactly what **Update now** does (steps 2 to 5 above): it asks GitHub once more, downloads the installer, checks its size and SHA-256, checks the file again right before running it, and installs it silently. Right before installing, it checks the quiet moment again, and that automatic updates and the update check are still switched on. If you switched them off, it throws the download away and installs nothing. If a game started or you opened the window, it keeps the checked download and installs it at the next quiet moment, without downloading it again, as long as GitHub still lists the same file.
3. OpenShaker comes back in the tray, never with a window and without a notification. The next time you open the window, the bar says "OpenShaker updated itself to X.Y.Z." (**What's new** opens that release), until the next update is offered or OpenShaker restarts.

A skipped version is never installed automatically. If an automatic update fails, that version is not tried again automatically, not even after a restart: the bar says why, and **Update now** is there as usual (a newer version is tried automatically again). A network problem is not a failure: it tries again 10 minutes later. Automatic updates need **Check for updates** on, work only for the installed copy, and wait while OpenShaker runs with `--no-start` or without its tray icon.

### Updating by hand

Download the new installer from the release page and run it. It asks the running OpenShaker to quit first, waiting up to about 10 s; that also works for a copy run from source. Only if a copy is still running after that does it ask you to close it. From 1.0.0 or 1.0.1, install 1.0.2 or later this way once; after that, **Update now** does it.

- Over an installed copy, its two boxes start from what you have now: **Start with Windows** is ticked only if OpenShaker starts with Windows now, and **Create a desktop shortcut** only if the shortcut is there. Unticking a box removes that entry.
- If you cancel it, or it stops before it has finished, the OpenShaker it closed is started again, in the tray.
- A silent update (`/SILENT` or `/VERYSILENT`) starts OpenShaker again, hidden, but only if it was running before, and keeps your current Start with Windows and desktop shortcut. If it stops after closing OpenShaker, it starts it again as described in [Update now](#update-now), step 6.

## Uninstalling

Go to **Settings > Apps > OpenShaker > Uninstall**. The uninstaller:
- asks a running copy to quit first;
- removes the Start with Windows entry;
- asks **"Also delete your OpenShaker settings (presets, strengths and logs)?"**. The default answer is **No**, which keeps them for a later reinstall.

A silent uninstall always keeps your settings.

## Tidies up after older versions

- Settings from an earlier version are copied into the settings folder once.
- Old preset names and layouts are converted.
- An old start-up entry called "ButtKicker Haptics" is renamed.
- A start-up entry that points to an old location (for example after the app folder moved) is fixed.

---

**Next:** [Shakers, amplifiers and channels](Shakers-Amplifiers-and-Channels.md)

**See also:** [Installing OpenShaker](Installing-OpenShaker.md) · [The settings file](Advanced-Settings.md#the-settings-file)
