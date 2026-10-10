import QtQuick
import QtQuick.Layouts
import "."

Card {
    id: root
    property string title: ""
    property real value: 0          // percent; negative means "not available"
    property color accent: Theme.accent

    readonly property bool available: value >= 0
    property real shown: available ? value : 0
    Behavior on shown { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }

    implicitHeight: 106

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 14
        anchors.bottomMargin: 16
        spacing: 6

        Text {
            text: root.title.toUpperCase()
            color: Theme.muted
            font.pixelSize: 11
            font.weight: Font.Bold
        }
        Text {
            text: root.available ? root.shown.toFixed(1) + "%" : "N/A"
            color: Theme.text
            font.pixelSize: 28
            font.weight: Font.DemiBold
        }
        Item { Layout.fillHeight: true }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 5
            radius: 2.5
            color: Theme.grid
            Rectangle {
                width: parent.width * Math.max(0, Math.min(100, root.shown)) / 100
                height: parent.height
                radius: parent.radius
                color: root.accent
            }
        }
    }
}
