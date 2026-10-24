import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

ApplicationWindow {
    id: win
    visible: true
    width: 1400
    height: 940
    minimumWidth: 1000
    minimumHeight: 680
    title: "FocusOS Monitor"
    color: Theme.bg
    font.pixelSize: 13

    property string issueText: ""
    property string clockText: ""

    readonly property var resourceSeries: [
        { label: "CPU", key: "cpu", colorKey: "cpu" },
        { label: "RAM", key: "ram", colorKey: "ram" },
        { label: "Disk", key: "disk", colorKey: "disk" },
        { label: "GPU", key: "gpu", colorKey: "gpu" }
    ]
    readonly property var processSeries: [
        { label: "Active", key: "active", colorKey: "green" },
        { label: "Background", key: "background", colorKey: "amber" },
        { label: "Suspended", key: "suspended", colorKey: "red" }
    ]
    readonly property var planColumns: [
        { title: "PID", w: 70, align: "right", muted: true },
        { title: "Name", w: 0 },
        { title: "CPU %", w: 80, align: "right" },
        { title: "RAM MB", w: 90, align: "right" },
        { title: "Class", w: 110, kind: "class" },
        { title: "Priority", w: 100 },
        { title: "Suspended", w: 100 }
    ]
    readonly property var memoryColumns: [
        { title: "PID", w: 70, align: "right", muted: true },
        { title: "Name", w: 0 },
        { title: "Memory MB", w: 100, align: "right" },
        { title: "Class", w: 110, kind: "class" }
    ]

    Binding { target: Theme; property: "dark"; value: backend.darkMode }

    onClosing: (close) => { close.accepted = backend.tryClose() }

    Connections {
        target: backend
        function onShutdownReady() { win.close() }
        function onShutdownIssue(text) {
            win.issueText = text
            issuePopup.open()
        }
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: win.clockText = Qt.formatDateTime(new Date(), "ddd dd MMM  HH:mm:ss")
    }

    // Wheel events: tables scroll first (if the cursor is over one and it can
    // move), otherwise the page scrolls. Everything is animated.
    function dispatchWheel(event) {
        var pixel = event.pixelDelta.y
        var delta = pixel !== 0 ? pixel : event.angleDelta.y
        if (delta === 0) return
        var target = pageScroll
        if (planTable.hovered && (planTable.scroller.canScroll(delta) || planTable.scroller.animating))
            target = planTable.scroller
        else if (memoryTable.hovered && (memoryTable.scroller.canScroll(delta) || memoryTable.scroller.animating))
            target = memoryTable.scroller
        if (pixel !== 0) target.scrollDirect(delta)
        else target.scrollSmooth(delta)
    }

    Flickable {
        id: page
        anchors.fill: parent
        clip: true
        interactive: false
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: content.implicitHeight + 52
        ScrollBar.vertical: ThinScrollBar {}

        ScrollHelper { id: pageScroll; flick: page; step: 1.0; duration: 240 }

        WheelHandler {
            onWheel: (event) => win.dispatchWheel(event)
        }

        ColumnLayout {
            id: content
            x: 28
            y: 24
            width: page.width - 56
            spacing: 18

            // Header
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                ColumnLayout {
                    spacing: 0
                    Text {
                        text: "FocusOS"
                        color: Theme.text
                        font.pixelSize: 22
                        font.weight: Font.Bold
                    }
                    Text {
                        text: "System performance and focus control"
                        color: Theme.muted
                    }
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: win.clockText
                    color: Theme.muted
                    font.pixelSize: 12
                }
                AppButton {
                    text: backend.darkMode ? "Light mode" : "Dark mode"
                    onClicked: backend.toggleTheme()
                }
                StatusBadge { status: backend.state.status }
            }

            // Controls
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AppButton { text: "Start"; kind: "primary"; enabled: backend.canStart; onClicked: backend.startRuntime() }
                AppButton { text: "Pause"; enabled: backend.canPause; onClicked: backend.pauseRuntime() }
                AppButton { text: "Resume"; enabled: backend.canResume; onClicked: backend.resumeRuntime() }
                AppButton { text: "Stop"; kind: "danger"; enabled: backend.canStop; onClicked: backend.stopRuntime() }
                AppButton { text: "Emergency disable"; kind: "danger"; enabled: backend.canStop; onClicked: backend.emergencyDisable() }
                AppButton { text: "Clean disk"; enabled: backend.canCleanDisk; onClicked: backend.cleanDisk() }
                Item { Layout.fillWidth: true }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Text {
                    text: "Resource policy"
                    color: Theme.text
                    font.weight: Font.DemiBold
                }
                Rectangle {
                    implicitWidth: autoProfileLabel.implicitWidth + 24
                    implicitHeight: 26
                    radius: height / 2
                    color: backend.resourceProfile === "focus" ? Theme.greenBg
                         : backend.resourceProfile === "performance" ? Theme.amberBg
                         : Theme.button
                    border.width: 1
                    border.color: backend.resourceProfile === "focus" ? Theme.greenBorder
                                : backend.resourceProfile === "performance" ? Theme.amberBorder
                                : Theme.borderStrong

                    Text {
                        id: autoProfileLabel
                        anchors.centerIn: parent
                        text: "Auto: " + backend.state.resourceProfile
                        font.pixelSize: 12
                        font.weight: Font.Bold
                        color: backend.resourceProfile === "focus" ? Theme.green
                             : backend.resourceProfile === "performance" ? Theme.amber
                             : Theme.text
                    }
                }
                ComboBox {
                    id: trainingTarget
                    readonly property var candidates: backend.state.trainingCandidates || []
                    Layout.preferredWidth: 250
                    enabled: backend.canChangeResourceProfile && !backend.state.mlPowerModeEnabled
                    textRole: "label"
                    model: candidates
                    displayText: candidates.length === 0
                        ? "No process available"
                        : currentIndex >= 0 ? currentText : "Select training process"
                    property int selectedPid: currentIndex >= 0 && currentIndex < candidates.length
                        ? candidates[currentIndex].pid : 0
                    implicitHeight: 38
                    font.pixelSize: 12
                    palette.text: Theme.text
                    palette.buttonText: Theme.text
                    background: Rectangle {
                        radius: 8
                        color: trainingTarget.enabled ? Theme.surface : Theme.buttonOffBg
                        border.color: trainingTarget.activeFocus ? Theme.accent : Theme.borderStrong
                        border.width: trainingTarget.activeFocus ? 2 : 1
                    }
                    contentItem: Text {
                        leftPadding: 12
                        rightPadding: 32
                        text: trainingTarget.displayText
                        font: trainingTarget.font
                        color: trainingTarget.enabled ? Theme.text : Theme.muted
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    indicator: Text {
                        x: trainingTarget.width - width - 12
                        y: (trainingTarget.height - height) / 2
                        text: trainingTarget.popup.visible ? "▴" : "▾"
                        color: Theme.muted
                        font.pixelSize: 13
                    }
                    delegate: ItemDelegate {
                        width: trainingTarget.width
                        highlighted: trainingTarget.highlightedIndex === index
                        contentItem: Text {
                            text: modelData.label
                            color: Theme.text
                            font: trainingTarget.font
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                        background: Rectangle {
                            color: parent.highlighted ? Theme.select : Theme.surface
                        }
                    }
                    popup: Popup {
                        y: trainingTarget.height + 4
                        width: trainingTarget.width
                        implicitHeight: Math.min(contentItem.implicitHeight, 280)
                        padding: 4
                        contentItem: ListView {
                            clip: true
                            implicitHeight: contentHeight
                            model: trainingTarget.popup.visible ? trainingTarget.delegateModel : null
                            currentIndex: trainingTarget.highlightedIndex
                            ScrollIndicator.vertical: ScrollIndicator {}
                        }
                        background: Rectangle {
                            color: Theme.surface
                            border.color: Theme.borderStrong
                            radius: 8
                        }
                    }
                }
                AppButton {
                    text: backend.state.mlPowerModeEnabled ? "Stop ML focus" : "Focus selected ML process"
                    enabled: backend.canChangeResourceProfile && (
                        backend.state.mlPowerModeEnabled || trainingTarget.selectedPid > 0
                    )
                    onClicked: backend.setMLPowerMode(
                        !backend.state.mlPowerModeEnabled,
                        trainingTarget.selectedPid
                    )
                }
                Rectangle {
                    implicitWidth: mlPowerLabel.implicitWidth + 24
                    implicitHeight: 26
                    radius: height / 2
                    visible: backend.state.mlPowerModeActive === true
                    color: Theme.dark ? "#3d1a6e" : "#f2e8ff"
                    border.width: 1
                    border.color: Theme.dark ? "#9b59b6" : "#c9a7ee"
                    Text {
                        id: mlPowerLabel
                        anchors.centerIn: parent
                        text: "Focused: " + backend.state.mlTrainingTargetName
                        font.pixelSize: 12
                        font.weight: Font.Bold
                        color: Theme.dark ? "#d7a8ff" : "#63349b"
                    }
                }

            }


            // Metric cards
            RowLayout {
                Layout.fillWidth: true
                spacing: 14
                MetricCard { Layout.fillWidth: true; Layout.preferredWidth: 1; title: "CPU"; value: backend.state.cpu; accent: Theme.cpu }
                MetricCard { Layout.fillWidth: true; Layout.preferredWidth: 1; title: "RAM"; value: backend.state.ram; accent: Theme.ram }
                MetricCard { Layout.fillWidth: true; Layout.preferredWidth: 1; title: "Disk"; value: backend.state.disk; accent: Theme.disk }
                MetricCard { Layout.fillWidth: true; Layout.preferredWidth: 1; title: "GPU"; value: backend.state.gpu; accent: Theme.gpu }
            }

            // Current focus
            Card {
                Layout.fillWidth: true
                implicitHeight: focusColumn.implicitHeight + 32

                ColumnLayout {
                    id: focusColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 20
                    anchors.topMargin: 16
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text {
                            text: "CURRENT FOCUS"
                            color: Theme.muted
                            font.pixelSize: 11
                            font.weight: Font.Bold
                        }
                        Item { Layout.fillWidth: true }
                        Chip { text: backend.state.focusMode }
                        Chip { text: backend.state.focusScore }
                    }
                    Text {
                        text: backend.state.mlPowerModeActive
                            ? "ML Training Focus: " + backend.state.mlTrainingTargetName
                            : backend.state.focusApp
                        color: Theme.text
                        font.pixelSize: 18
                        font.weight: Font.Bold
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    Text {
                        text: backend.state.mlPowerModeActive
                            ? "Selected training process (PID " + backend.state.mlTrainingTargetPid + ")"
                            : backend.state.focusWindow
                        color: Theme.muted
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                    }
                    Text {
                        text: backend.state.warningText
                        color: backend.state.warningActive ? Theme.red : Theme.green
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                    }
                }
            }

            // Charts
            RowLayout {
                Layout.fillWidth: true
                spacing: 14
                LineChart {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 300
                    title: "Resource usage (%)"
                    series: win.resourceSeries
                    samples: backend.history
                    fixedScale: true
                }
                LineChart {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 300
                    title: "Process counts"
                    series: win.processSeries
                    samples: backend.history
                    fixedScale: false
                }
            }

            // Tables
            RowLayout {
                Layout.fillWidth: true
                spacing: 14
                DataTable {
                    id: planTable
                    Layout.fillWidth: true
                    Layout.preferredWidth: 2
                    Layout.preferredHeight: 480
                    title: "Process priority plan"
                    columns: win.planColumns
                    model: backend.planModel
                    smoothScrolling: true
                }
                DataTable {
                    id: memoryTable
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 480
                    title: "Top memory consumers"
                    columns: win.memoryColumns
                    model: backend.memoryModel
                }
            }

            // Footer
            Text {
                text: backend.state.summary
                color: Theme.muted
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }
            Text {
                text: backend.message
                visible: text.length > 0
                color: backend.messageKind === "error" ? Theme.red
                      : backend.messageKind === "warn" ? Theme.amber : Theme.muted
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }
        }
    }

    // Shown only if the runtime could not restore everything on exit
    Popup {
        id: issuePopup
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 460
        padding: 22
        closePolicy: Popup.NoAutoClose

        background: Rectangle {
            color: Theme.surface
            border.color: Theme.borderStrong
            radius: 12
        }
        contentItem: ColumnLayout {
            spacing: 14
            Text {
                text: "Shutdown warning"
                color: Theme.text
                font.pixelSize: 16
                font.weight: Font.Bold
            }
            Text {
                text: win.issueText
                color: Theme.text
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            AppButton {
                text: "OK"
                kind: "primary"
                Layout.alignment: Qt.AlignRight
                onClicked: {
                    issuePopup.close()
                    backend.finishShutdown()
                }
            }
        }
    }
}
