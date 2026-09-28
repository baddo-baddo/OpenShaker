# Start with Windows, updates and uninstalling

[OpenShaker guide](README.md) › Using OpenShaker

How Start with Windows works, how updates install, what the uninstaller removes, and what OpenShaker tidies up after older versions.

## Start with Windows

This is a single entry named **OpenShaker** in your Windows sign-in list (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). It starts `OpenShaker.exe --hidden`, straight into the tray. You can switch it on or off with the installer option, the window checkbox or the tray menu. All three change the same entry.

## Updating

Run the new installer. It asks the running copy to quit first, waiting up to about 10 s. If a copy is still running (for example one started from source), it asks you to close it. A silent update (`/SILENT` or `/VERYSILENT`) starts OpenShaker again, hidden, but only if it was running before.

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
