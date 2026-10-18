import Cocoa

// hotkey <modifiers> <keycode> — posts a keystroke to whatever has the
// keyboard. Modifiers: c=cmd s=shift a=alt t=ctrl, in any order.
//   hotkey c 9   # Cmd+V
//   hotkey "" 36 # Return
let mods = CommandLine.arguments[1]
let code = CGKeyCode(UInt16(CommandLine.arguments[2])!)
var flags: CGEventFlags = []
if mods.contains("c") { flags.insert(.maskCommand) }
if mods.contains("s") { flags.insert(.maskShift) }
if mods.contains("a") { flags.insert(.maskAlternate) }
if mods.contains("t") { flags.insert(.maskControl) }
for down in [true, false] {
    let e = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down)
    e?.flags = flags
    e?.post(tap: .cghidEventTap)
    usleep(45_000)
}
