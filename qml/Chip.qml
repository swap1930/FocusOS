import QtQuick
import "."

Rectangle {
    id: root
    property alias text: label.text

    implicitWidth: label.implicitWidth + 22
    implicitHeight: 24
    radius: height / 2
    color: Theme.button
    border.color: Theme.borderStrong
    border.width: 1

    Text {
        id: label
        anchors.centerIn: parent
        color: Theme.muted
        font.pixelSize: 12
        font.weight: Font.DemiBold
    }
}
