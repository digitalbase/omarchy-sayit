-- Add these to ~/.config/hypr/bindings.lua after checking for conflicts.
-- F9 remains Voxtype push-to-talk.
o.bind("F10", "Read selected text", "sayit selection --detach")
o.bind("SHIFT + F10", "Read clipboard", "sayit clipboard --detach")
o.bind("CTRL + F10", "Pause or resume speech", "sayit toggle")
o.bind("ALT + F10", "Stop speech", "sayit stop")
o.bind("SUPER + F10", "Speech player", "sayit ui")

