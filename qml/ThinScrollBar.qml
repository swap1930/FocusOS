import QtQuick
import QtQuick.Controls.Basic
import "."

ScrollBar {
    id: bar
    policy: ScrollBar.AlwaysOn
    minimumSize: 0.08
    padding: 2
    implicitWidth: 12

    contentItem: Rectangle {
        implicitWidth: 6
        radius: 3
        color: Theme.scroll
        visible: bar.size < 1.0
        opacity: bar.pressed ? 1.0 : (bar.hovered ? 0.9 : 0.6)
        Behavior on opacity { NumberAnimation { duration: 150 } }
    }
    background: Item {}
}
