import AppKit
import Foundation

private let cacheURL = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent(".cache/ai-resource-hud/status.json")

private final class MenuFields {
    let usage: NSMenuItem
    let reset: NSMenuItem
    let source: NSMenuItem
    let state: NSMenuItem
    let snapshot: NSMenuItem

    init(usage: NSMenuItem, reset: NSMenuItem, source: NSMenuItem, state: NSMenuItem, snapshot: NSMenuItem) {
        self.usage = usage
        self.reset = reset
        self.source = source
        self.state = state
        self.snapshot = snapshot
    }
}

final class StatusController: NSObject, NSApplicationDelegate {
    private let definitions: [(key: String, label: String, provider: String, metric: String)] = [
        ("AG", "AG", "antigravity", "geminiFiveHour"),
        ("CG", "CC", "antigravity", "claudeGptFiveHour"),
        ("C", "C", "codex", "fiveHour"),
        ("ALI", "ALI", "alibabatokenplan", "sevenDay")
    ]
    private var statusItems: [(key: String, label: String, item: NSStatusItem)] = []
    private var fields: [String: MenuFields] = [:]
    private var refreshTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        for definition in definitions {
            let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
            item.behavior = .removalAllowed
            item.button?.font = NSFont.monospacedDigitSystemFont(ofSize: 10.5, weight: .regular)
            item.button?.toolTip = definition.label
            item.menu = makeMenu(for: definition)
            statusItems.append((definition.key, definition.label, item))
        }
        refresh()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            self?.refresh()
        }
        if let refreshTimer {
            RunLoop.main.add(refreshTimer, forMode: .common)
        }
    }

    private func makeMenu(for definition: (key: String, label: String, provider: String, metric: String)) -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false

        let heading = NSMenuItem(title: "\(definition.label) quota", action: nil, keyEquivalent: "")
        heading.isEnabled = false
        menu.addItem(heading)
        menu.addItem(.separator())

        let usage = NSMenuItem(title: "Remaining: --", action: nil, keyEquivalent: "")
        usage.isEnabled = false
        let reset = NSMenuItem(title: "Reset: --", action: nil, keyEquivalent: "")
        reset.isEnabled = false
        let source = NSMenuItem(title: "Source: --", action: nil, keyEquivalent: "")
        source.isEnabled = false
        let state = NSMenuItem(title: "State: unavailable", action: nil, keyEquivalent: "")
        state.isEnabled = false
        let snapshot = NSMenuItem(title: "Snapshot: --", action: nil, keyEquivalent: "")
        snapshot.isEnabled = false

        menu.addItem(usage)
        menu.addItem(reset)
        menu.addItem(source)
        menu.addItem(state)
        menu.addItem(snapshot)
        fields[definition.key] = MenuFields(usage: usage, reset: reset, source: source, state: state, snapshot: snapshot)
        return menu
    }

    private func readRoot() -> [String: Any]? {
        guard let data = try? Data(contentsOf: cacheURL),
              let object = try? JSONSerialization.jsonObject(with: data),
              let root = object as? [String: Any] else {
            return nil
        }
        return root
    }

    private func record(root: [String: Any], provider: String) -> [String: Any]? {
        guard let providers = root["providers"] as? [String: Any],
              let value = providers[provider] as? [String: Any] else {
            return nil
        }
        return value
    }

    private func metric(record: [String: Any]?, name: String) -> [String: Any]? {
        guard let record,
              let metrics = record["metrics"] as? [String: Any],
              let value = metrics[name] as? [String: Any] else {
            return nil
        }
        return value
    }

    private func percent(_ metric: [String: Any]?) -> String {
        guard let metric,
              let number = metric["remainingPercent"] as? NSNumber else {
            return "--"
        }
        let value = max(0, min(100, number.doubleValue))
        if abs(value.rounded() - value) < 0.01 {
            return String(Int(value.rounded()))
        }
        return String(format: "%.1f", value)
    }

    private func reset(_ metric: [String: Any]?) -> String {
        guard let metric, let value = metric["resetAt"] as? String, !value.isEmpty else {
            return "--"
        }
        return value
    }

    private func remainingTime(_ metric: [String: Any]?) -> String {
        guard let metric,
              let value = metric["resetAt"] as? String,
              !value.isEmpty else {
            return "--"
        }

        let formatter = ISO8601DateFormatter()
        guard let resetDate = formatter.date(from: value) else {
            return "--"
        }

        let totalSeconds = max(0, Int(resetDate.timeIntervalSinceNow))

        let days = totalSeconds / 86400
        let hours = (totalSeconds % 86400) / 3600
        let minutes = (totalSeconds % 3600) / 60

        if days > 0 {
            return "\(days)d\(hours)h"
        }

        if hours > 0 {
            return "\(hours)h\(minutes)m"
        }

        return "\(minutes)m"
    }

    private func detailText(_ label: String, _ metric: [String: Any]?) -> String {
    let value = percent(metric)

    guard metric != nil, value != "--" else {
        return "\(label): --"
    }

    let numeric = Double(value) ?? 0

    if numeric >= 99.995 {
        return "\(label): \(value)% · ready"
    }

    if numeric <= 0 {
        return "\(label): \(value)% · \(remainingTime(metric))"
    }

    let remaining = remainingTime(metric)

    if numeric < 10 {
        return "\(label): \(value)% · \(remaining) !!"
    }

    if numeric < 30 {
        return "\(label): \(value)% · \(remaining) !"
    }

    return "\(label): \(value)% · \(remaining)"
}

private func snapshot(_ root: [String: Any]?) -> String {
        guard let root, let value = root["snapshotAt"] as? String else {
            return "--"
        }
        return value
    }

    private func refresh() {
        let root = readRoot()
        for definition in definitions {
            let providerRecord: [String: Any]?
            if let root {
                providerRecord = self.record(root: root, provider: definition.provider)
            } else {
                providerRecord = nil
            }
            let metricValue = self.metric(record: providerRecord, name: definition.metric)
            let providerState = providerRecord?["status"] as? String ?? "unavailable"
            let source = providerRecord?["source"] as? String ?? "unknown"
            let value = percent(metricValue)
            let isAvailable = metricValue != nil && value != "--"
            let displayState = isAvailable ? providerState : "unavailable"
            let suffix = displayState == "stale" ? " STALE" : (displayState == "ready" ? "" : " · UNAVAILABLE")

            if let entry = statusItems.first(where: { $0.key == definition.key }) {
                if isAvailable {
                    let remaining = remainingTime(metricValue)
                    let numericValue = Double(value) ?? 0

                    let statusText: String
                    if numericValue >= 99.995 {
                        statusText = "ready"
                    } else if numericValue <= 0 {
                        statusText = "stop"
                    } else if numericValue < 10 {
                        statusText = "\(value)% · \(remaining) !!"
                    } else if numericValue < 30 {
                        statusText = "\(value)% · \(remaining) !"
                    } else {
                        statusText = "\(value)% · \(remaining)"
                    }

                    entry.item.button?.title = "\(definition.label) \(statusText)\(suffix)"
                } else {
                    entry.item.button?.title = "\(definition.label) -- · UNAVAILABLE"
                }
            }
            guard let menu = fields[definition.key] else { continue }
            let weeklyName: String?
            switch definition.key {
            case "AG":
                weeklyName = "geminiWeekly"
            case "CG":
                weeklyName = "claudeGptWeekly"
            case "C":
                weeklyName = "weekly"
            default:
                weeklyName = nil
            }

            if definition.key == "ALI" {
                menu.usage.title = detailText("Weekly", metricValue)
                menu.reset.isHidden = true
            } else {
                menu.usage.title = detailText("5H", metricValue)
                let weeklyMetric = weeklyName.flatMap {
                    self.metric(record: providerRecord, name: $0)
                }
                menu.reset.title = detailText("Weekly", weeklyMetric)
                menu.reset.isHidden = false
            }

            menu.source.isHidden = true
            menu.snapshot.isHidden = true

            if !isAvailable {
                menu.state.title = "Status: unavailable"
            } else if (Double(value) ?? 0) >= 99.995 {
                menu.state.title = "Status: ready"
            } else if (Double(value) ?? 0) <= 0 {
                menu.state.title = "Status: stop"
            } else {
                menu.state.title = "Status: active"
            }
        }
    }
}

let application = NSApplication.shared
let delegate = StatusController()
application.delegate = delegate
application.run()
