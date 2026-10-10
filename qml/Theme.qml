pragma Singleton
import QtQuick

// Colour tokens for both themes. Every colour animates when `dark` flips.
QtObject {
    id: theme

    property bool dark: false
    readonly property int transitionDuration: 260

    property color bg: dark ? "#0d1117" : "#f4f6f9"
    property color surface: dark ? "#161b22" : "#ffffff"
    property color surfaceAlt: dark ? "#12171e" : "#f7f9fb"
    property color border: dark ? "#262d38" : "#dde2ea"
    property color borderStrong: dark ? "#30394a" : "#c9d1dc"
    property color text: dark ? "#e6edf3" : "#1f2937"
    property color muted: dark ? "#8b97a8" : "#667085"
    property color accent: dark ? "#2f81f7" : "#2563eb"
    property color accentHover: dark ? "#4893ff" : "#1d4fd8"
    property color accentText: "#ffffff"
    property color button: dark ? "#1c232d" : "#ffffff"
    property color buttonHover: dark ? "#252e3b" : "#eef2f7"
    property color buttonOffText: dark ? "#4d5766" : "#a5aebb"
    property color buttonOffBg: dark ? "#12171e" : "#f1f3f6"
    property color green: dark ? "#3fb950" : "#16803c"
    property color amber: dark ? "#d29922" : "#b7791f"
    property color red: dark ? "#f85149" : "#d92d20"
    property color greenBg: dark ? "#12261a" : "#e7f6ec"
    property color greenBorder: dark ? "#1f4a2b" : "#b7e1c3"
    property color amberBg: dark ? "#2a2111" : "#fdf3dc"
    property color amberBorder: dark ? "#4d3b14" : "#f0d89a"
    property color redBg: dark ? "#2d1618" : "#fdecea"
    property color redBorder: dark ? "#5c2a2e" : "#f4c2bd"
    property color grid: dark ? "#232a35" : "#e8ecf2"
    property color select: dark ? "#1f3a5f" : "#dbe7fb"
    property color scroll: dark ? "#3a4558" : "#c3ccd8"
    property color cpu: dark ? "#58a6ff" : "#2563eb"
    property color ram: dark ? "#bc8cff" : "#7c3aed"
    property color disk: dark ? "#e3b341" : "#d97706"
    property color gpu: dark ? "#39c5bb" : "#0d9488"

    Behavior on bg { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on surface { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on surfaceAlt { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on border { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on borderStrong { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on text { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on muted { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on accent { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on accentHover { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on button { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on buttonHover { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on buttonOffText { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on buttonOffBg { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on green { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on amber { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on red { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on greenBg { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on greenBorder { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on amberBg { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on amberBorder { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on redBg { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on redBorder { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on grid { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on select { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on scroll { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on cpu { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on ram { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on disk { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
    Behavior on gpu { ColorAnimation { duration: theme.transitionDuration; easing.type: Easing.InOutCubic } }
}
