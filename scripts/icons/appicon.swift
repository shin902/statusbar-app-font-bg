import AppKit

// appicon list                      -> "<localizedName>\t<bundlePath>" for every regular running app
// appicon icon <App.app> <out.png> [size] -> the icon as shown in Finder/Dock, rendered to PNG
let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("usage: appicon list | appicon icon <App.app> <out.png> [size]\n".data(using: .utf8)!)
    exit(2)
}

switch args[1] {
case "list":
    for app in NSWorkspace.shared.runningApplications where app.activationPolicy == .regular {
        print("\(app.localizedName ?? "")\t\(app.bundleURL?.path ?? "")")
    }
case "icon":
    let size = args.count > 4 ? Int(args[4])! : 1024
    let img = NSWorkspace.shared.icon(forFile: args[2])
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    img.draw(in: NSRect(x: 0, y: 0, width: size, height: size))
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[3]))
default:
    exit(2)
}
