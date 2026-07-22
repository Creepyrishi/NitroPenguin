# Upstream bug reports: brightness keys on the Acer Nitro AN515-45

Two related problems were diagnosed on Ubuntu 26.04 (gnome-shell 50.1,
kernel 7.0.0-28) on the Acer Nitro AN515-45. Draft reports below; file
them at the linked trackers and paste the findings.

## 1. gnome-shell: BrightnessScale stepDown becomes a silent no-op

Where to file: https://gitlab.gnome.org/GNOME/gnome-shell/-/issues

Summary: after `screen-brightness-cycle` wraps the global scale to 0.0
(`BrightnessScale.cycleUp()` in `js/misc/brightnessManager.js` sets the
value to 0.0 when at max), the `screen-brightness-down` keybinding
becomes a silent no-op: `stepDown()` clamps at 0.0, no OSD is shown, no
backlight write happens. Adjusting brightness with the quick-settings
slider does not re-seed the global scale, so the down key stays dead
until the user presses brightness-up. The up key keeps working the whole
time, which makes this look like a hardware fault to users.

Reproduction (also triggerable on any machine by binding a spare key to
screen-brightness-cycle):

1. Screen brightness at maximum.
2. Trigger `screen-brightness-cycle` once: OSD appears, brightness
   wraps to minimum (expected cycle behavior).
3. Press XF86MonBrightnessDown: nothing happens, no OSD (bug).
4. Press XF86MonBrightnessUp once: works, and afterwards the down key
   recovers.

Hardware detail that makes it worse: the panel (amdgpu, custom
brightness curve) reports backlight min 603 / max 60395, so "minimum"
still emits light and users do not realize the scale hit the floor.

Suggested behavior: show the OSD even when the step clamps at a bound
(feedback that the key was received), and keep the global scale synced
with external absolute changes (slider, D-Bus SetBacklight).

## 2. systemd hwdb: Nitro AN515-45 keyboard-backlight Fn keys

Where to file: https://github.com/systemd/systemd (PR against
`hwdb.d/60-keyboard.hwdb`)

Summary: the generic Acer block (`evdev:atkbd:dmi:...svnAcer*:pn*`)
predates the Nitro line. On the Nitro AN515-45, the keyboard-backlight
keys leak scancodes with wrong or missing mappings:

- Fn+F9 (backlight dim): scancode index `f0` (raw `e070`) is unmapped;
  the kernel logs `atkbd serio0: Unknown key pressed ... e070`.
- Fn+F10 (backlight brighten): its leaked scancode is mapped by the
  legacy block to a meaning from older Aspire models; on GNOME this
  reaches `screen-brightness-cycle`, which slams the SCREEN brightness
  to minimum while the user is only adjusting the keyboard backlight
  (and then triggers bug 1 above).
- The same chords occasionally leak bare Ctrl/Shift make codes without
  break codes, leaving stuck modifiers until the user taps those keys.

Proposed stanza (scancode for F10 to be confirmed with
`evtest`/MSC_SCAN on the device):

```
# Acer Nitro AN515-45 keyboard backlight keys
evdev:atkbd:dmi:bvn*:bvr*:bd*:svnAcer*:pnNitroAN515-45:*
 KEYBOARD_KEY_f0=kbdillumdown                           # Fn+F9
 KEYBOARD_KEY_<f10-index>=kbdillumup                    # Fn+F10
```

The EC performs the actual backlight change itself; these mappings only
make the OS see semantically correct key events.
