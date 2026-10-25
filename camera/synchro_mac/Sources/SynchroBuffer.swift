import Foundation

/// Readable byte queue with a cursor.
/// Consumed prefixes are compacted in chunks so each Bluetooth fragment
/// does not shift the whole JPEG buffer.
struct SynchroByteBuffer {
    private var storage: [UInt8] = []
    private var start = 0

    var count: Int { storage.count - start }
    var allocatedCount: Int { storage.count }
    var isEmpty: Bool { count == 0 }

    mutating func reset() {
        storage.removeAll(keepingCapacity: true)
        start = 0
    }

    mutating func append(_ data: Data) {
        guard !data.isEmpty else { return }
        compactIfNeeded()
        if storage.capacity < storage.count + data.count {
            storage.reserveCapacity(max(storage.capacity * 2, storage.count + data.count, 4096))
        }
        storage.append(contentsOf: data)
    }

    mutating func dropFirst(_ length: Int) {
        guard length > 0 else { return }
        if length >= count {
            reset()
            return
        }
        start += length
        compactIfNeeded()
    }

    func firstIndex(of byte: UInt8) -> Int? {
        guard start < storage.count else { return nil }
        guard let absolute = storage[start..<storage.count].firstIndex(of: byte) else { return nil }
        return absolute - start
    }

    func copyPrefix(_ length: Int) -> Data {
        guard length > 0 else { return Data() }
        return Data(storage[start..<(start + length)])
    }

    func matches(_ needle: Data, at offset: Int) -> Bool {
        guard offset >= 0, needle.count <= count - offset else { return false }
        let begin = start + offset
        for (index, byte) in needle.enumerated() where storage[begin + index] != byte {
            return false
        }
        return true
    }

    private mutating func compactIfNeeded() {
        guard start > 0 else { return }
        if start >= 65_536 || (start > 4_096 && start * 2 > storage.count) {
            storage.removeFirst(start)
            start = 0
        }
    }
}
