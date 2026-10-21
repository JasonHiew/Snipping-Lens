![JasonHiew/Snipping-Lens](https://github.com/RisPNG/Snipping-Lens/blob/main/banner.png)

<p align="center">
<a href="https://github.com/JasonHiew/Snipping-Lens/stargazers"><img alt="GitHub Repo Stars" src="https://img.shields.io/github/stars/JasonHiew/Snipping-Lens?style=flat&color=limegreen"></a>
<a href="https://github.com/JasonHiew/Snipping-Lens"><img alt="GitHub Last Commit" src="https://img.shields.io/github/last-commit/JasonHiew/Snipping-Lens?style=flat&color=lightyellow"></a>
</p>

> **Fork modifications** (on top of upstream v5):
>
> - Images are uploaded to [uguu.se](https://uguu.se) instead of Litterbox.
> - After Google Lens opens, clicking **Copy** on detected text opens it in your default search site — [jpdb.io](https://jpdb.io) out of the box, useful for Japanese vocabulary lookup. Add or edit sites (e.g. `https://www.trainchinese.com/v2/search.php?searchWord=<search_term>`) in the config window under **Clipboard Search Sites**; `<search_term>` is replaced with the copied text.
> - The tray menu has an **Auto Upload to Google Lens** toggle and a **Default Search Site** switcher.
>
> Original project by [RisPNG](https://github.com/RisPNG/Snipping-Lens).

- Found a coding video but cannot copy the code?
- You're a dyslexic or know a dyslexic fella that has trouble spelling and copying things properly?
- Need texts from meetings share screen?
- Found a meme and wanna reverse search its origin?
- Want to quickly translate foreign text from screenshots?
- Working with scanned documents or textbooks?

Snipping Lens gotchu!

Snipping Lens is a cross-platform application that automatically detects when you take screenshots and searches them using Google Lens for quick image lookup, and text extraction and translation.

## Sections

1. [Installation](#installation)
2. [Usage](#usage)
3. [Requirements](#requirements)
4. [FAQ](#faq)
5. [Building from Source](#building-from-source)
6. [Support and Contributing](#support-and-contributing)
7. [Disclaimer](#disclaimer)

## Demo

https://github.com/user-attachments/assets/56979ab6-48e1-4112-af36-c053e9e17089

Current demo is for older versions.

## Installation

Check [Releases](https://github.com/RisPNG/Snipping-Lens/releases) for the latest release and installation instructions.

## Usage

### Taking Screenshots

**Windows:**

- Use Win+Shift+S, Print Screen, the configured hotkey, or left-click the tray icon.
- Any of those opens the Windows Snipping Tool; the capture it puts on your clipboard is detected and opened in Google Lens.
- Images copied from anywhere else are ignored, so ordinary copying never uploads anything.

**Linux:**

- Use the configured hotkey (default: Alt + Ctrl + \\), or click "Snip" from the tray icon.
- On X11, Snipping Lens shows its own region selection overlay and captures the screen directly.
- On Wayland, the screenshot is taken through your desktop's XDG Desktop Portal, which shows its own selection UI.
- The captured screenshot is also copied to your clipboard.

### Tray Icon Actions

- **Left-click** (Windows only): Takes a regional screenshot with the snipping tool.
- **Right-click** (_and also left-click for Linux_): Show context menu with options:
  - **Snip**: Takes a screenshot (Linux only).
  - **Open App**: Opens Snipping Lens main window.
  - **Auto Upload to Google Lens**: Turns the upload and Lens search on or off.
  - **Default Search Site**: Picks which site copied text from Lens opens in.
  - **Exit**: Close the application.

## Requirements

- An Internet connection, and access to [uguu.se](https://uguu.se) and [Google](https://google.com).

### Windows

- Windows 10 or later.

### Linux

- No screenshot tools needed. X11 is supported out of the box; on Wayland your desktop must provide the XDG Screenshot portal (GNOME, KDE and most modern desktops do). If it is missing, the log suggests the backend package to install for your desktop.

## FAQ

### Where are my screenshots uploaded? Are they stored permanently?

Screenshots are uploaded to [uguu.se](https://uguu.se), a free and anonymous temporary file hosting service, solely for the purpose of generating a URL that can be used with Google Lens. Files uploaded to uguu.se are not stored permanently and are automatically deleted after 24 hours. No user information is attached to the upload, and the application does not keep any record of your screenshots.

### Why not use the locally stored image to query Google Lens?

Simplicity, getting an image from user's clipboard and uploading it to a file hosting site is more straightforward than figuring out where the image is saved on the device for each operating system.

I'm sure you're worried about privacy, but you shouldn't be uploading confidential information to Google in the first place anyway.

### Limitations & Longevity

As long as uguu.se returns the expected response (a direct image URL) and as long as the Google Lens endpoint `https://lens.google.com/uploadbyurl?url=<uploaded_image_url>` still exists and works, this program will continue to function as intended. If either service changes or is discontinued, the program's automatic search feature may no longer work.

## Building from Source

Both `setup_win.vbs` (Windows) and `setup_linux.sh` (Linux) build the application from source using their own portable Python environment ([MsPy](https://github.com/RisPNG/MsPy) 3.11). The application code lives in `src/`. If you want to use your own Python environment, adjust the interpreter path in `bin/win/install.bat` on Windows, or in `setup_linux.sh` on Linux.

## Support and Contributing

If you like this project, please leave a star 🌟, and share it with your friends! Consider donating on [PayPal](https://paypal.me/rispng) to support development. _I will soon do Ko-Fi instead.

If you encounter any issue:

1. Check the [issues page](https://github.com/RisPNG/Snipping-Lens/issues) if issue has been raised.
2. Create a new issue if necessary and provide in-depth details of the issue including the relevant logs. The last lines are shown in the app window (tray > Open App); the full log is at `bin/win/logs/sniplens.log` on Windows and `bin/linux/logs/sniplens.log` on Linux.

## Disclaimer

This project comes with no guarantee or warranty. You are responsible for whatever happens from using this project. This is a personal project and is in no way affiliated with Google nor Microsoft.
