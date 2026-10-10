import QtQuick
import "."

// Plain line chart drawn on a Canvas: grid, time axis, crisp lines, hover read-out.
// Samples advance from the left toward the right edge.
Card {
    id: root
    property string title: ""
    // [{ label: "CPU", key: "cpu", colorKey: "cpu" }, ...]
    property var series: []
    // [{ t: "12:00:01", cpu: 10.0, ... }, ...]
    property var samples: []
    property bool fixedScale: true
    property int window: 120
    property real hoverX: -1

    implicitHeight: 300
    onSamplesChanged: canvas.requestPaint()
    onHoverXChanged: canvas.requestPaint()

    // Repaint throughout the shared theme transition so canvas colors stay in sync.
    Connections {
        target: Theme
        function onBgChanged() { canvas.requestPaint() }
    }

    HoverHandler {
        id: hover
        onHoveredChanged: if (!hovered) root.hoverX = -1
        onPointChanged: if (hovered) root.hoverX = point.position.x
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        renderTarget: Canvas.FramebufferObject
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()

        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)

            var left = 46, top = 50, right = 20, bottom = 62
            var pw = width - left - right
            var ph = height - top - bottom
            var data = root.samples || []
            var n = data.length
            var win = Math.max(2, root.window)
            var ser = root.series

            ctx.textBaseline = "alphabetic"
            ctx.textAlign = "left"
            ctx.font = "600 13px sans-serif"
            ctx.fillStyle = Theme.text
            ctx.fillText(root.title, 18, 30)
            ctx.font = "12px sans-serif"

            if (n === 0) {
                ctx.fillStyle = Theme.muted
                ctx.textAlign = "center"
                ctx.fillText("Waiting for samples...", left + pw / 2, top + ph / 2)
                return
            }

            // Scale
            var maxV = 100
            if (!root.fixedScale) {
                var m = 0
                for (var a = 0; a < n; a++)
                    for (var b = 0; b < ser.length; b++) {
                        var vv = data[a][ser[b].key]
                        if (vv !== null && vv !== undefined && vv > m) m = vv
                    }
                maxV = Math.max(4, Math.ceil(m * 1.2 / 4) * 4)
            }

            function xAt(i) { return left + pw * i / (win - 1) }
            function yAt(v) { return top + ph - Math.min(v, maxV) / maxV * ph }

            // Horizontal grid + y labels
            ctx.lineWidth = 1
            ctx.strokeStyle = Theme.grid
            ctx.fillStyle = Theme.muted
            ctx.textAlign = "right"
            ctx.textBaseline = "middle"
            for (var g = 0; g <= 4; g++) {
                var gy = Math.round(top + ph - ph * g / 4) + 0.5
                ctx.beginPath(); ctx.moveTo(left, gy); ctx.lineTo(left + pw, gy); ctx.stroke()
                ctx.fillText(String(Math.round(maxV * g / 4)), left - 8, gy)
            }

            // Vertical grid + time labels
            ctx.textBaseline = "alphabetic"
            for (var k = 0; k < 5; k++) {
                var gx = Math.round(left + pw * k / 4) + 0.5
                ctx.strokeStyle = Theme.grid
                ctx.beginPath(); ctx.moveTo(gx, top); ctx.lineTo(gx, top + ph); ctx.stroke()
                var idx = Math.round(k * (win - 1) / 4)
                if (idx >= 0 && idx < n) {
                    ctx.fillStyle = Theme.muted
                    ctx.textAlign = k === 0 ? "left" : (k === 4 ? "right" : "center")
                    ctx.fillText(String(data[idx].t), gx, top + ph + 18)
                }
            }

            // Plot frame
            ctx.strokeStyle = Theme.borderStrong
            ctx.strokeRect(left + 0.5, top + 0.5, pw, ph)

            // Lines, clipped to the plot area
            ctx.save()
            ctx.beginPath(); ctx.rect(left, top - 2, pw + 1, ph + 4); ctx.clip()
            ctx.lineWidth = 1.8
            ctx.lineJoin = "round"
            ctx.lineCap = "round"
            var latest = []
            for (var s = 0; s < ser.length; s++) {
                ctx.strokeStyle = Theme[ser[s].colorKey]
                ctx.beginPath()
                var started = false
                var last = null
                for (var i = 0; i < n; i++) {
                    var v = data[i][ser[s].key]
                    if (v === null || v === undefined) { started = false; continue }
                    if (!started) { ctx.moveTo(xAt(i), yAt(v)); started = true }
                    else ctx.lineTo(xAt(i), yAt(v))
                    last = v
                }
                ctx.stroke()
                latest.push(last)
            }
            ctx.restore()

            function fmt(v) { return root.fixedScale ? v.toFixed(1) + "%" : String(Math.round(v)) }

            // Hover read-out
            if (root.hoverX >= left && root.hoverX <= left + pw) {
                var hi = Math.round((root.hoverX - left) / pw * (win - 1))
                if (hi >= 0 && hi < n) {
                    var hx = Math.round(xAt(hi)) + 0.5
                    ctx.strokeStyle = Theme.borderStrong
                    ctx.lineWidth = 1
                    ctx.beginPath(); ctx.moveTo(hx, top); ctx.lineTo(hx, top + ph); ctx.stroke()

                    var lines = [String(data[hi].t)]
                    for (var q = 0; q < ser.length; q++) {
                        var hv = data[hi][ser[q].key]
                        if (hv === null || hv === undefined) continue
                        ctx.fillStyle = Theme[ser[q].colorKey]
                        ctx.beginPath(); ctx.arc(hx, yAt(hv), 3.5, 0, Math.PI * 2); ctx.fill()
                        lines.push(ser[q].label + "  " + fmt(hv))
                    }
                    ctx.font = "12px sans-serif"
                    var bw = 0
                    for (var w = 0; w < lines.length; w++)
                        bw = Math.max(bw, ctx.measureText(lines[w]).width)
                    bw += 22
                    var bh = lines.length * 18 + 10
                    var bx = hx + 12
                    if (bx + bw > left + pw) bx = hx - 12 - bw
                    var by = top + 8
                    var r = 6
                    ctx.beginPath()
                    ctx.moveTo(bx + r, by)
                    ctx.arcTo(bx + bw, by, bx + bw, by + bh, r)
                    ctx.arcTo(bx + bw, by + bh, bx, by + bh, r)
                    ctx.arcTo(bx, by + bh, bx, by, r)
                    ctx.arcTo(bx, by, bx + bw, by, r)
                    ctx.closePath()
                    ctx.fillStyle = Theme.surfaceAlt
                    ctx.fill()
                    ctx.strokeStyle = Theme.borderStrong
                    ctx.stroke()
                    ctx.textAlign = "left"
                    ctx.textBaseline = "alphabetic"
                    for (var z = 0; z < lines.length; z++) {
                        ctx.fillStyle = z === 0 ? Theme.muted : Theme.text
                        ctx.fillText(lines[z], bx + 11, by + 18 + z * 18 - 3)
                    }
                }
            }

            // Legend with current values
            var lx = left
            var ly = height - 18
            ctx.textAlign = "left"
            ctx.textBaseline = "alphabetic"
            for (var e = 0; e < ser.length; e++) {
                if (latest[e] === null || latest[e] === undefined) continue
                ctx.strokeStyle = Theme[ser[e].colorKey]
                ctx.lineWidth = 2.5
                ctx.beginPath(); ctx.moveTo(lx, ly - 4); ctx.lineTo(lx + 14, ly - 4); ctx.stroke()
                var text = ser[e].label + "  " + Math.round(latest[e])
                ctx.fillStyle = Theme.text
                ctx.fillText(text, lx + 20, ly)
                lx += 20 + ctx.measureText(text).width + 24
            }
        }
    }
}
