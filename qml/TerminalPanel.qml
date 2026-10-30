import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Card {
    id: root
    property var outputRows: backend.terminalOutput
    property var suggestions: backend.terminalSuggestions
    property string commandText: ""
    property string workingDirectory: backend.terminalWorkingDirectory
    property int selectedIndex: -1
    property var commandHistory: backend.terminalHistory
    property int historyIndex: -1
    property bool terminalMode: false
    Layout.fillWidth: true
    Layout.fillHeight: terminalMode
    implicitHeight: terminalMode ? 650 : terminalColumn.implicitHeight + 36

    function updateSuggestions() {
        suggestionTimer.restart()
    }
    function updateOutputScroll() {
        outputScrollTimer.restart()
    }
    function acceptSelectedSuggestion() {
        if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
            commandText = suggestions[selectedIndex].command
            selectedIndex = -1
            input.forceActiveFocus()
        } else if (suggestions.length > 0) {
            commandText = suggestions[0].command
            selectedIndex = -1
            input.forceActiveFocus()
        }
    }
    function runCommand() {
        if (commandText.trim().length === 0) return
        var command = commandText.trim()
        historyIndex = -1
        backend.terminalRun(command)
        commandText = ""
        selectedIndex = -1
        updateSuggestions()
    }

    Timer {
        id: suggestionTimer
        interval: 240
        repeat: false
        onTriggered: backend.terminalSuggest(root.commandText)
    }
    Timer {
        id: outputScrollTimer
        interval: 40
        repeat: false
        onTriggered: if (outputView.count > 0) outputView.positionViewAtEnd()
    }

    ColumnLayout {
        id: terminalColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 18
        spacing: 12


        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "AI TERMINAL"
                color: Theme.text
                font.pixelSize: 14
                font.weight: Font.Bold
            }
            Rectangle {
                radius: height / 2
                implicitWidth: aiLabel.implicitWidth + 18
                implicitHeight: 25
                color: backend.terminalAIAvailable ? Theme.greenBg : Theme.buttonOffBg
                border.color: backend.terminalAIAvailable ? Theme.greenBorder : Theme.border
                Text {
                    id: aiLabel
                    anchors.centerIn: parent
                    text: backend.terminalBusy ? "AI thinking…" : backend.terminalAIAvailable ? "AI available" : "Local suggestions"
                    color: backend.terminalAIAvailable ? Theme.green : Theme.muted
                    font.pixelSize: 11
                }
            }
            Text {
                text: "FocusOS " + backend.state.status.toLowerCase() + " · " + root.workingDirectory
                color: Theme.muted
                elide: Text.ElideMiddle
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                font.pixelSize: 11
            }
            AppButton { text: "Clear"; onClicked: backend.terminalClear() }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: root.terminalMode
            Layout.preferredHeight: root.terminalMode ? 420 : Math.min(260, Math.max(112, outputView.contentHeight + 24))
            color: Theme.dark ? "#090d12" : "#101722"
            radius: 8
            border.color: Theme.borderStrong
            ListView {
                id: outputView
                anchors.fill: parent
                anchors.margins: 12
                clip: true
                spacing: 8
                model: root.outputRows
                delegate: Column {
                    width: outputView.width
                    spacing: 3
                    Text {
                        width: parent.width
                        text: "> " + modelData.command + "  [exit " + modelData.returncode + "]"
                        color: "#7ee787"
                        font.family: "monospace"
                        wrapMode: Text.Wrap
                    }
                    Text {
                        width: parent.width
                        visible: modelData.stdout.length > 0
                        text: modelData.stdout
                        color: "#e6edf3"
                        font.family: "monospace"
                        wrapMode: Text.Wrap
                    }
                    Text {
                        width: parent.width
                        visible: modelData.stderr.length > 0
                        text: modelData.stderr
                        color: "#ff7b72"
                        font.family: "monospace"
                        wrapMode: Text.Wrap
                    }
                }
                onCountChanged: root.updateOutputScroll()
            }
        }

        Item {
            Layout.fillWidth: true
            implicitHeight: suggestionList.visible ? Math.min(root.terminalMode ? 190 : 156, suggestionList.contentHeight + 8) : 0
            visible: height > 0
            ListView {
                id: suggestionList
                anchors.fill: parent
                clip: true
                visible: root.commandText.length > 0 && root.suggestions.length > 0
                model: root.suggestions
                delegate: Rectangle {
                    required property int index
                    required property var modelData
                    width: suggestionList.width
                    height: 34
                    radius: 5
                    color: index === root.selectedIndex ? Theme.select : (mouse.containsMouse ? Theme.buttonHover : "transparent")
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        Text { text: modelData.command; color: Theme.text; font.family: "monospace" }
                        Text { text: modelData.source === "ai" ? "AI" : "LOCAL"; color: Theme.accent; font.pixelSize: 10 }
                        Text { text: modelData.explanation; color: Theme.muted; elide: Text.ElideRight; Layout.fillWidth: true }
                    }
                    MouseArea {
                        id: mouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            root.selectedIndex = index
                            root.acceptSelectedSuggestion()
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: root.terminalMode ? 54 : 42
            radius: 7
            color: Theme.surfaceAlt
            border.width: input.activeFocus ? 2 : 1
            border.color: input.activeFocus ? Theme.accent : Theme.borderStrong
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 8
                spacing: 6
                Text { text: ">"; color: Theme.green; font.family: "monospace"; font.pixelSize: 15 }
                TextField {
                    id: input
                    Layout.fillWidth: true
                    text: root.commandText
                    onTextChanged: {
                        if (root.commandText !== text) root.commandText = text
                        root.selectedIndex = -1
                        root.updateSuggestions()
                    }
                    placeholderText: root.terminalMode ? "Describe a task or enter a supported command…" : "Type a supported development command…"
                    color: Theme.text
                    placeholderTextColor: Theme.muted
                    font.family: "monospace"
                    background: Item {}
                    cursorDelegate: Rectangle { width: 1; color: Theme.accent; visible: input.activeFocus }
                    Keys.onPressed: (event) => {
                        if (event.key === Qt.Key_Down) {
                            if (root.suggestions.length > 0)
                                root.selectedIndex = Math.min(root.selectedIndex + 1, root.suggestions.length - 1)
                            event.accepted = true
                        } else if (event.key === Qt.Key_Up) {
                            if (root.selectedIndex >= 0) root.selectedIndex = Math.max(0, root.selectedIndex - 1)
                            else if (root.commandHistory.length > 0) {
                                if (root.historyIndex < 0) root.historyIndex = root.commandHistory.length - 1
                                else root.historyIndex = Math.max(0, root.historyIndex - 1)
                                root.commandText = root.commandHistory[root.historyIndex]
                            }
                            event.accepted = true
                        } else if (event.key === Qt.Key_Tab) {
                            root.acceptSelectedSuggestion()
                            event.accepted = true
                        } else if (event.key === Qt.Key_Escape) {
                            root.selectedIndex = -1
                            root.commandText = ""
                            backend.terminalSuggest("")
                            event.accepted = true
                        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            if (root.selectedIndex >= 0) root.acceptSelectedSuggestion()
                            else root.runCommand()
                            event.accepted = true
                        }
                    }
                }
                Text {
                    text: input.activeFocus ? "▍" : ""
                    color: Theme.accent
                    font.family: "monospace"
                    SequentialAnimation on opacity {
                        running: input.activeFocus
                        loops: Animation.Infinite
                        NumberAnimation { to: 0; duration: 550 }
                        NumberAnimation { to: 1; duration: 550 }
                    }
                }
            }
        }
        Text {
            text: root.terminalMode
                  ? "FocusOS terminal · " + root.workingDirectory + " · AI requests map to allowlisted commands only; general shell execution is disabled."
                  : "Allowlisted commands only, scoped to the FocusOS project directory. AI suggestions require separate confirmation; general shell execution is disabled."
            color: Theme.muted
            font.pixelSize: 11
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
    }
}
