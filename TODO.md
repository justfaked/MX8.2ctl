# cherry-util – TODO

Command-line tool to configure the CHERRY MX 8.2 TKL Wireless on Bazzite, run from distrobox.

## v1 (in build order)

- [x] Find the keyboard's dongle (046a:01c3) and open a connection to it (hidraw)
- [x] Read the battery level (read-only)
- [x] Read the current sleep and hibernate settings (read-only safety check)
- [x] `cherry-util battery`: print the battery percentage
- [x] `cherry-util sleep`: set sleep (30–300 s or off) and hibernate (15–300 min or off), only after the read check looks sensible
- [x] `cherry-util lighting`: set effect, color, brightness and speed
- [x] Find out whether the keyboard remembers settings after power-off (it does)
- [x] Named presets in a settings file; `cherry-util save|use|presets|delete`
- [x] Remember the last-used preset
- [x] ~~Re-apply the last-used preset automatically on login/reconnect~~ (not needed: the keyboard remembers its settings)
- [x] Export `cherry-util` from distrobox so it runs in a normal Bazzite terminal
- [x] Short usage notes (README)
- [x] Graphical app: lighting, sleep settings, battery level and presets in a window, launchable from the app menu
- [x] System tray icon showing the current battery level (updates on its own, starts with login)

## Later

- [ ] Low-battery desktop notification
- [ ] Per-key colors
- [ ] Support the USB cable connection
- [ ] Maybe publish on GitHub for other MX 8.2 owners

## Out of scope

- Key remapping (use keyd or input-remapper instead)
- Macros
- Polling rate
- Bluetooth
- Anything that needs Windows

## Safety rules

- Only send commands that others have confirmed, or that come from Cherry's own software
- Read before writing; stop if the values look odd
- Never send anything that looks like a firmware update or memory write
