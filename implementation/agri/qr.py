from .vendor.qrencoder import QRCode, QR8bitByte, QRErrorCorrectLevel

def make_svg(value):
    qr = QRCode(None, QRErrorCorrectLevel.M)
    qr.addData(QR8bitByte(value))
    qr.make()
    n = qr.getModuleCount()
    quiet = 4
    path = []
    for y in range(n):
        for x in range(n):
            if qr.isDark(y, x):
                path.append(f'M{x+quiet},{y+quiet}h1v1h-1z')
    size=n+quiet*2
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" role="img" aria-label="产品溯源二维码"><rect width="{size}" height="{size}" fill="white"/><path d="{"".join(path)}" fill="black" shape-rendering="crispEdges"/></svg>'
