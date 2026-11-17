// Jev Hotkey: a tiny login-item helper. It owns Control-Option-J system-wide. When the hotkey is pressed it opens
// Jev if Jev is closed (passing --show-orb), or tells the running Jev to show its orb. No windows, no Dock icon.
// It uses only a Carbon hotkey (no Accessibility or Input Monitoring) and NSWorkspace. Original code for Jev.
import AppKit
import Carbon.HIToolbox

let jevBundleID = "com.heyjev.app"
let showOrbNotification = "com.heyjev.app.showOrb"

// Same physical-key table and validation as area_hotkey.summon_shortcut; no event tap.
func shortcut(_ raw: String) -> (UInt32, UInt32)? {
    let codes: [UInt32] = [0,11,8,2,14,3,5,4,34,38,40,37,46,45,31,35,12,15,1,17,32,9,13,7,16,6]
    let letters = Array("abcdefghijklmnopqrstuvwxyz").map(String.init)
    let parts = raw.lowercased().split(separator: "+", omittingEmptySubsequences: false).map(String.init)
    let flags: [String: UInt32] = ["ctrl": UInt32(controlKey), "alt": UInt32(optionKey),
                                  "cmd": UInt32(cmdKey), "shift": UInt32(shiftKey)]
    guard parts.count >= 2, let key = parts.last, let index = letters.firstIndex(of: key) else { return nil }
    let mods = Array(parts.dropLast())
    guard Set(mods).count == mods.count, mods.allSatisfy({ flags[$0] != nil }) else { return nil }
    let mask = mods.reduce(UInt32(0)) { $0 | flags[$1]! }
    guard !(key == "w" && mask == UInt32(controlKey | optionKey | cmdKey)) else { return nil }
    return (codes[index], mask)
}

final class Helper: NSObject, NSApplicationDelegate {
    var hotKeyRef: EventHotKeyRef?
    var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ -> OSStatus in
            helper.fire()
            return noErr
        }, 1, &spec, nil, nil)
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didLaunchApplicationNotification, object: nil, queue: .main
        ) { _ in self.register() }
        register()
        // While Jev is running it may hold the same hotkey. Try again every 2 seconds, and at once when Jev quits.
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { _ in self.register() }
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didTerminateApplicationNotification, object: nil, queue: .main
        ) { note in
            let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            if app?.bundleIdentifier == jevBundleID { self.register() }
        }
    }

    func register() {
        // Jev owns the shortcut while running. Yield promptly, then reacquire on termination.
        if !NSRunningApplication.runningApplications(withBundleIdentifier: jevBundleID).isEmpty {
            if let ref = hotKeyRef { UnregisterEventHotKey(ref); hotKeyRef = nil }
            return
        }
        if hotKeyRef != nil { return }
        var ref: EventHotKeyRef?
        let id = EventHotKeyID(signature: OSType(0x4A45_5648), id: 1)  // "JEVH"
        let defaults = UserDefaults(suiteName: jevBundleID)
        defaults?.synchronize()
        let raw = defaults?.string(forKey: "summon_shortcut") ?? "ctrl+alt+j"
        guard let chord = shortcut(raw) ?? shortcut("ctrl+alt+j") else { return }
        let status = RegisterEventHotKey(chord.0, chord.1, id,
                                         GetApplicationEventTarget(), 0, &ref)
        if status == noErr { hotKeyRef = ref }
        else { NSLog("Jev shortcut unavailable (Carbon status %d)", status) }
    }

    func fire() {
        if !NSRunningApplication.runningApplications(withBundleIdentifier: jevBundleID).isEmpty {
            DistributedNotificationCenter.default().postNotificationName(
                NSNotification.Name(showOrbNotification), object: nil, userInfo: nil, deliverImmediately: true)
            return
        }
        guard let url = jevURL() else { return }
        let config = NSWorkspace.OpenConfiguration()
        config.arguments = ["--show-orb"]
        config.activates = false
        NSWorkspace.shared.openApplication(at: url, configuration: config, completionHandler: nil)
    }

    // The helper sits at <Jev>.app/Contents/Library/LoginItems/Jev Hotkey.app, so Jev is four levels up.
    func jevURL() -> URL? {
        var url = Bundle.main.bundleURL
        for _ in 0..<4 { url.deleteLastPathComponent() }
        // Only the containing installed app is trusted. Never ask Launch Services to choose a duplicate.
        let allowed = ["/Applications/", NSHomeDirectory() + "/Applications/"]
        func permitted(_ candidate: URL) -> Bool {
            allowed.contains(where: { candidate.path.hasPrefix($0) }) &&
            !candidate.pathComponents.contains(where: { $0.lowercased().contains("jarvis") }) &&
            !candidate.path.contains("/Mobile Documents/") && candidate.pathExtension == "app"
        }
        // Reject excluded lexical paths before filesystem resolution or bundle inspection.
        guard permitted(url) else { return nil }
        url = url.resolvingSymlinksInPath().standardizedFileURL
        guard permitted(url), Bundle(url: url)?.bundleIdentifier == jevBundleID else { return nil }
        return url
    }
}

let helper = Helper()
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
app.delegate = helper
app.run()
