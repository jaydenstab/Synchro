import CoreGraphics
import Foundation
import ImageIO

enum SynchroImage {
    /// Decodes a JPEG off the main thread. Returns nil for truncated or corrupt bytes.
    static func decode(_ data: Data) -> CGImage? {
        let options = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, options) else { return nil }
        return CGImageSourceCreateImageAtIndex(source, 0, options)
    }
}
