import QtQuick
import QtQuick.Controls.Basic
import "."

Button {
    id: control
    property string kind: "default"   // "default" | "primary" | "danger"

    implicitHeight: 36
    leftPadding: 18
    rightPadding: 18
    hoverEnabled: true
    font.weight: Font.DemiBold

    contentItem: Text {
        text: control.text
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: !control.enabled ? Theme.buttonOffText
              : control.kind === "primary" ? Theme.accentText
              : control.kind === "danger" ? Theme.red : Theme.text
    }

    background: Rectangle {
        radius: 7
        border.width: 1
        opacity: control.down ? 0.85 : 1.0
        color: !control.enabled ? Theme.buttonOffBg
              : control.kind === "primary" ? (control.hovered ? Theme.accentHover : Theme.accent)
              : control.kind === "danger" ? (control.hovered ? Theme.redBg : Theme.button)
              : (control.hovered ? Theme.buttonHover : Theme.button)
        border.color: !control.enabled ? Theme.border
                     : control.kind === "primary" ? Theme.accent
                     : control.kind === "danger" ? Theme.redBorder : Theme.borderStrong
        Behavior on opacity { NumberAnimation { duration: 80 } }
    }

    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
