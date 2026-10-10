import QtQuick

// Animated wheel scrolling for a Flickable. The Flickable itself is made
// non-interactive; this helper drives contentY.
Item {
    id: root
    required property Flickable flick
    property real step: 1.0
    property int duration: 240
    property bool retarget: false
    property real goal: 0
    readonly property bool animating: anim.running || retargetTimer.running
    visible: false

    function minY() { return flick.originY - flick.topMargin }
    function maxY() {
        return Math.max(minY(), flick.originY + flick.contentHeight + flick.bottomMargin - flick.height)
    }
    function base() { return animating ? goal : flick.contentY }

    // delta > 0 scrolls up, delta < 0 scrolls down (same sign as wheel angleDelta)
    function canScroll(delta) {
        var b = base()
        return delta > 0 ? b > minY() + 0.5 : b < maxY() - 0.5
    }

    function scrollSmooth(delta) {
        var t = Math.max(minY(), Math.min(maxY(), base() - delta * step))
        goal = t
        if (root.retarget) {
            anim.stop()
            retargetTimer.lastTick = Date.now()
            if (!retargetTimer.running) retargetTimer.start()
            return
        }
        retargetTimer.stop()
        anim.stop()
        anim.from = flick.contentY
        anim.to = t
        anim.start()
    }

    function scrollDirect(delta) {
        retargetTimer.stop()
        anim.stop()
        flick.contentY = Math.max(minY(), Math.min(maxY(), flick.contentY - delta))
    }

    Timer {
        id: retargetTimer
        interval: 16
        repeat: true
        property double lastTick: 0

        onTriggered: {
            var now = Date.now()
            var elapsed = Math.max(1, now - lastTick)
            lastTick = now
            var distance = root.goal - root.flick.contentY
            if (Math.abs(distance) < 0.5) {
                root.flick.contentY = root.goal
                stop()
                return
            }
            var progress = 1 - Math.exp(-elapsed / 65)
            root.flick.contentY += distance * progress
        }
    }

    NumberAnimation {
        id: anim
        target: root.flick
        property: "contentY"
        duration: root.duration
        easing.type: Easing.OutCubic
    }
}
