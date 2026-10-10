import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Card {
    id: root
    property string title: ""
    // [{ title: "PID", w: 70, align: "right", muted: true, kind: "class" }, ...]
    // w: 0 makes the column stretch.
    property var columns: []
    property alias model: list.model
    property int rowHeight: 34
    property bool smoothScrolling: false

    readonly property alias scroller: scroll
    readonly property bool hovered: hover.hovered
    readonly property real contentW: Math.max(0, list.width - 12)
    readonly property real fixedSum: {
        var s = 0
        for (var i = 0; i < columns.length; i++) s += columns[i].w
        return s
    }

    function colWidth(col) {
        return col.w > 0 ? col.w : Math.max(80, contentW - fixedSum)
    }

    function classColor(c) {
        var k = String(c).toLowerCase()
        if (k === "active" || k === "foreground") return Theme.green
        if (k === "background") return Theme.amber
        if (k === "suspended") return Theme.red
        return Theme.muted
    }

    HoverHandler { id: hover }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        anchors.bottomMargin: 10
        spacing: 8

        Text {
            text: root.title
            color: Theme.text
            font.pixelSize: 14
            font.weight: Font.Bold
        }

        // Header row
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            Row {
                Repeater {
                    model: root.columns
                    delegate: Text {
                        required property var modelData
                        width: root.colWidth(modelData)
                        height: 32
                        leftPadding: 8
                        rightPadding: 8
                        text: modelData.title
                        color: Theme.muted
                        font.pixelSize: 12
                        font.weight: Font.Bold
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                        elide: Text.ElideRight
                    }
                }
            }
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.border
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: list
                anchors.fill: parent
                clip: true
                interactive: false
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                ScrollBar.vertical: ThinScrollBar {}

                delegate: Rectangle {
                    id: row
                    required property int index
                    required property var cells
                    required property string cls

                    width: ListView.view.width
                    height: root.rowHeight
                    color: rowHover.hovered ? Theme.select
                          : (index % 2 === 1 ? Theme.surfaceAlt : "transparent")

                    HoverHandler { id: rowHover }

                    Row {
                        Repeater {
                            model: root.columns
                            delegate: Text {
                                required property var modelData
                                required property int index
                                width: root.colWidth(modelData)
                                height: root.rowHeight
                                leftPadding: 8
                                rightPadding: 8
                                verticalAlignment: Text.AlignVCenter
                                horizontalAlignment: modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
                                elide: Text.ElideRight
                                text: row.cells && row.cells[index] !== undefined ? row.cells[index] : ""
                                color: modelData.kind === "class" ? root.classColor(row.cls)
                                      : (modelData.muted ? Theme.muted : Theme.text)
                            }
                        }
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: list.count === 0
                text: "No data"
                color: Theme.muted
            }
        }
    }

    ScrollHelper {
        id: scroll
        flick: list
        step: root.smoothScrolling ? 1.0 : 0.8
        duration: root.smoothScrolling ? 220 : 200
        retarget: root.smoothScrolling
    }
}
