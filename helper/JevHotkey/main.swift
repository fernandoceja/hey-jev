// Jev Hotkey: a tiny login-item helper. It owns Control-Option-J system-wide. When the hotkey is pressed it opens
// Jev if Jev is closed (passing --show-orb), or tells the running Jev to show its orb. No windows, no Dock icon.
// It uses only a Carbon hotkey (no Accessibility or Input Monitoring) and NSWorkspace. Original code for Jev.
import AppKit
import Carbon.HIToolbox

let jevBundleID = "com.heyjev.app"
let showOrbNotification = "com.heyjev.app.showOrb"

final class Helper: NSObject, NSApplicationDelegate {
    var hotKeyRef: EventHotKeyRef?
    var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ -> OSStatus in
            helper.fire()
            return noErr
        }, 1, &spec, nil, nil)
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
        if hotKeyRef != nil { return }
        var ref: EventHotKeyRef?
        let id = EventHotKeyID(signature: OSType(0x4A45_5648), id: 1)  // "JEVH"
        let status = RegisterEventHotKey(UInt32(kVK_ANSI_J), UInt32(controlKey | optionKey), id,
                                         GetApplicationEventTarget(), 0, &ref)
        if status == noErr { hotKeyRef = ref }
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
        if url.pathExtension == "app" { return url }
        return NSWorkspace.shared.urlForApplication(withBundleIdentifier: jevBundleID)
    }
}

let helper = Helper()
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
app.delegate = helper
app.run()
