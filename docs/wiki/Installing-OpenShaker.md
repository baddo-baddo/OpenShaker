# Installing OpenShaker

[OpenShaker guide](README.md) › Getting started

How to download and install OpenShaker, what the installer does, and the first things to do once it runs.

## Download and install

1. Download **OpenShaker-Setup-&lt;version&gt;.exe** from the [latest release](https://github.com/baddo-baddo/OpenShaker/releases/latest). If your browser says the file isn't commonly downloaded, choose **Keep** (in Edge: **...** > **Keep** > **Show more** > **Keep anyway**).
2. Double-click it. The installer is not code-signed, so Windows may show **"Windows protected your PC"**: click **More info**, then **Run anyway**.
3. Click **Install**. That is the only screen.

## What the installer does

- The installer installs **for your Windows account only**, with **no admin prompt**, to `%LOCALAPPDATA%\Programs\OpenShaker`. It needs 64-bit Windows.
- There is **one screen** with two options, both ticked by default:
  - **Start OpenShaker with Windows (it waits in the notification area)**
  - **Create a desktop shortcut**

  Run over an installed copy, the boxes start from what you have now instead, and unticking one removes that entry ([Updating by hand](Start-With-Windows-Updates-and-Uninstalling.md#updating-by-hand)).
- A Start menu entry is always created.
- OpenShaker **starts as soon as installation finishes and opens its window**. There is no "Finished" page. Closing the window keeps it running in the notification area.
- The licence and third-party notices are installed next to the program.

## First run

1. **Turn your shaker's amplifier down.**
2. In the OpenShaker window, choose your shaker **by name** under **Output > Device**, not "(Windows default output)": if the shaker is unplugged, Windows makes your speakers the default output.
3. Press **Test tone** and raise the amplifier until the sweep feels firm but never clatters. The test tone is described on [The main window](The-Main-Window.md#buttons-along-the-bottom).
4. Set up your game (next page) and drive. OpenShaker switches to that game's preset by itself.

## What a new install starts with

- Haptics on
- Device "ButtKicker", Left channel
- Master 100 %, every strength 100 %
- Forza Motorsport preset until a game is detected
- Each effect on or off as its preset ships

---

**Next:** [Setting up your games](Setting-Up-Your-Games.md)

**See also:** [Safety](Safety.md) · [Shakers, amplifiers and channels](Shakers-Amplifiers-and-Channels.md) · [Start with Windows, updates and uninstalling](Start-With-Windows-Updates-and-Uninstalling.md)
