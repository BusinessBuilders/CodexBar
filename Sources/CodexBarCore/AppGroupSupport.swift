import Foundation

public enum AppGroupSupport {
    public static let teamID = "Y5PE65HELJ"
    public static let releaseGroupID = "\(teamID).com.steipete.codexbar"
    public static let debugGroupID = "\(teamID).com.steipete.codexbar.debug"
    public static let legacyReleaseGroupID = "group.com.steipete.codexbar"
    public static let legacyDebugGroupID = "group.com.steipete.codexbar.debug"
    public static let widgetSnapshotFilename = "widget-snapshot.json"
    public static let migrationVersion = 1
    public static let migrationVersionKey = "appGroupMigrationVersion"

    private static let migratedDefaultsKeys = [
        "debugDisableKeychainAccess",
        "widgetSelectedProvider",
    ]

    public struct MigrationResult: Sendable {
        public enum Status: String, Sendable {
            case alreadyCompleted
            case targetUnavailable
            case noChangesNeeded
            case migrated
        }

        public let status: Status
        public let copiedDefaultsKeys: [String]
        public let copiedSnapshot: Bool

        public init(status: Status, copiedDefaultsKeys: [String] = [], copiedSnapshot: Bool = false) {
            self.status = status
            self.copiedDefaultsKeys = copiedDefaultsKeys.sorted()
            self.copiedSnapshot = copiedSnapshot
        }
    }

    public static func currentGroupID(for bundleID: String? = Bundle.main.bundleIdentifier) -> String {
        self.isDebugBundleID(bundleID) ? self.debugGroupID : self.releaseGroupID
    }

    public static func legacyGroupID(for bundleID: String? = Bundle.main.bundleIdentifier) -> String {
        self.isDebugBundleID(bundleID) ? self.legacyDebugGroupID : self.legacyReleaseGroupID
    }

    public static func sharedDefaults(
        bundleID: String? = Bundle.main.bundleIdentifier,
        fileManager: FileManager = .default)
        -> UserDefaults?
    {
        guard self.currentContainerURL(bundleID: bundleID, fileManager: fileManager) != nil else { return nil }
        return UserDefaults(suiteName: self.currentGroupID(for: bundleID))
    }

    public static func currentContainerURL(
        bundleID: String? = Bundle.main.bundleIdentifier,
        fileManager: FileManager = .default)
        -> URL?
    {
        #if os(macOS)
        fileManager.containerURL(forSecurityApplicationGroupIdentifier: self.currentGroupID(for: bundleID))
        #else
        nil
        #endif
    }

    public static func snapshotURL(
        bundleID: String? = Bundle.main.bundleIdentifier,
        fileManager: FileManager = .default,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser)
        -> URL
    {
        if let container = self.currentContainerURL(bundleID: bundleID, fileManager: fileManager) {
            return container.appendingPathComponent(self.widgetSnapshotFilename, isDirectory: false)
        }

        let directory = self.localFallbackDirectory(fileManager: fileManager, homeDirectory: homeDirectory)
        return directory.appendingPathComponent(self.widgetSnapshotFilename, isDirectory: false)
    }

    public static func localFallbackDirectory(
        fileManager: FileManager = .default,
        homeDirectory _: URL = FileManager.default.homeDirectoryForCurrentUser)
        -> URL
    {
        let base = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? fileManager.temporaryDirectory
        let directory = base.appendingPathComponent("CodexBar", isDirectory: true)
        try? fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    public static func legacyContainerCandidateURL(
        bundleID: String? = Bundle.main.bundleIdentifier,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser)
        -> URL
    {
        homeDirectory
            .appendingPathComponent("Library", isDirectory: true)
            .appendingPathComponent("Group Containers", isDirectory: true)
            .appendingPathComponent(self.legacyGroupID(for: bundleID), isDirectory: true)
    }

    public static func migrateLegacyDataIfNeeded(
        bundleID: String? = Bundle.main.bundleIdentifier,
        standardDefaults: UserDefaults = .standard,
        fileManager: FileManager = .default,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
        currentDefaultsOverride: UserDefaults? = nil,
        legacyDefaultsOverride: UserDefaults? = nil,
        currentSnapshotURLOverride: URL? = nil,
        legacySnapshotURLOverride: URL? = nil)
        -> MigrationResult
    {
        if standardDefaults.integer(forKey: self.migrationVersionKey) >= self.migrationVersion {
            return MigrationResult(status: .alreadyCompleted)
        }

        let currentDefaults = currentDefaultsOverride
            ?? self.sharedDefaults(bundleID: bundleID, fileManager: fileManager)
        guard let currentDefaults else {
            return MigrationResult(status: .targetUnavailable)
        }

        let legacyDefaults = legacyDefaultsOverride ?? UserDefaults(suiteName: self.legacyGroupID(for: bundleID))
        let currentSnapshotURL = currentSnapshotURLOverride
            ?? self.currentContainerURL(bundleID: bundleID, fileManager: fileManager)?
            .appendingPathComponent(self.widgetSnapshotFilename, isDirectory: false)
        let legacySnapshotURL = legacySnapshotURLOverride
            ?? self.legacyContainerCandidateURL(bundleID: bundleID, homeDirectory: homeDirectory)
            .appendingPathComponent(self.widgetSnapshotFilename, isDirectory: false)

        var copiedDefaultsKeys: [String] = []
        for key in self.migratedDefaultsKeys {
            guard currentDefaults.object(forKey: key) == nil,
                  let value = legacyDefaults?.object(forKey: key)
            else {
                continue
            }
            currentDefaults.set(value, forKey: key)
            copiedDefaultsKeys.append(key)
        }

        let copiedSnapshot = {
            guard let currentSnapshotURL else { return false }
            guard !fileManager.fileExists(atPath: currentSnapshotURL.path),
                  fileManager.fileExists(atPath: legacySnapshotURL.path)
            else {
                return false
            }
            do {
                try fileManager.createDirectory(
                    at: currentSnapshotURL.deletingLastPathComponent(),
                    withIntermediateDirectories: true)
                try fileManager.copyItem(at: legacySnapshotURL, to: currentSnapshotURL)
                return true
            } catch {
                return false
            }
        }()

        let result = if copiedDefaultsKeys.isEmpty, !copiedSnapshot {
            MigrationResult(status: .noChangesNeeded)
        } else {
            MigrationResult(
                status: .migrated,
                copiedDefaultsKeys: copiedDefaultsKeys,
                copiedSnapshot: copiedSnapshot)
        }

        standardDefaults.set(self.migrationVersion, forKey: self.migrationVersionKey)
        return result
    }

    private static func isDebugBundleID(_ bundleID: String?) -> Bool {
        guard let bundleID, !bundleID.isEmpty else { return false }
        return bundleID.contains(".debug")
    }
}
