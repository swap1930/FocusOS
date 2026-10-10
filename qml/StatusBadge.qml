import QtQuick
import "."

Rectangle {
    id: root
    property string status: "STOPPED"
    readonly property string kind: status === "RUNNING" ? "running"
                                  : status === "PAUSED" ? "paused" : "stopped"

    implicitWidth: label.implicitWidth + 28
    implicitHeight: 26
    radius: height / 2
    color: kind === "running" ? Theme.greenBg : kind === "paused" ? Theme.amberBg : Theme.button
    border.width: 1
    border.color: kind === "running" ? Theme.greenBorder
                 : kind === "paused" ? Theme.amberBorder : Theme.borderStrong

    Text {
        id: label
        anchors.centerIn: parent
        text: root.status
        font.pixelSize: 12
        font.weight: Font.Bold
        color: root.kind === "running" ? Theme.green
              : root.kind === "paused" ? Theme.amber : Theme.muted
    }
}
