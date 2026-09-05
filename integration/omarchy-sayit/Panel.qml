import QtQuick
import Qt5Compat.GraphicalEffects
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "digitalbase.sayit"
  ipcTarget: "digitalbase.sayit"
  property var snapshot: ({state: "offline", current: null, position: 0, duration: 0, rate: 1})
  property var history: []
  property string errorMessage: ""
  readonly property bool online: snapshot.state !== "offline"
  readonly property bool playing: snapshot.state === "playing"
  readonly property bool generating: snapshot.state === "generating" || !!(snapshot.current && snapshot.current.state === "generating")
  readonly property string selectionShortcut: snapshot.shortcuts ? snapshot.shortcuts.selection : "F10"
  readonly property string clipboardShortcut: snapshot.shortcuts ? snapshot.shortcuts.clipboard : ""
  readonly property bool busy: playing || snapshot.state === "paused" || snapshot.state === "generating"
  readonly property string stateLabel: {
    if (!online) return "Service is stopped"
    if (snapshot.state === "generating") return "Preparing speech…"
    if (snapshot.state === "playing") return "Reading aloud"
    if (snapshot.state === "paused") return "Paused"
    if (snapshot.state === "failed") return "Speech failed"
    return "Ready to read"
  }
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property real rowHoverOverflow: Style.space(6)
  implicitWidth: barButton.implicitWidth
  implicitHeight: barButton.implicitHeight

  function execute(args) {
    if (action.running) return
    errorMessage = ""
    action.command = ["sayit"].concat(args)
    action.running = true
  }
  function playPause() {
    if (!busy && snapshot.current && snapshot.current.audio) execute(["replay", snapshot.current.id])
    else execute(["toggle"])
  }
  function refreshHistory() { if (!historyProcess.running) historyProcess.running = true }
  onOpenedChanged: if (opened) refreshHistory()

  Process {
    id: statusProcess
    command: ["sayit", "status", "--follow"]
    running: true
    stdout: SplitParser {
      onRead: function(line) {
        try { root.snapshot = JSON.parse(line) } catch (e) { root.errorMessage = "Could not read player status" }
      }
    }
    onExited: { root.snapshot = {state: "offline", current: null, position: 0, duration: 0, rate: 1}; retry.restart() }
  }
  Timer { id: retry; interval: 3000; onTriggered: statusProcess.running = true }
  Process {
    id: action
    stdout: StdioCollector {}
    stderr: StdioCollector { id: actionError; waitForEnd: true }
    onExited: function(code) {
      if (code !== 0) root.errorMessage = String(actionError.text || "Action failed").trim()
      if (root.opened) root.refreshHistory()
    }
  }
  Process {
    id: historyProcess
    command: ["sayit", "history"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try { root.history = JSON.parse(text).filter(function(job) { return !!job.audio }).slice(0, 4) }
        catch (e) { root.history = [] }
      }
    }
  }

  BarIconButton {
    id: barButton
    bar: root.bar
    active: root.busy
    tooltipText: "SayIt · " + root.stateLabel + "\nClick to open · Right-click to pause/resume"
    iconComponent: Component {
      Item {
        Image {
          id: sayitIcon
          anchors.fill: parent
          source: "sayit.svg"
          sourceSize.width: 64
          sourceSize.height: 64
          fillMode: Image.PreserveAspectFit
          visible: false
        }
        ColorOverlay {
          anchors.fill: sayitIcon
          source: sayitIcon
          id: animatedIcon
          color: root.busy || root.generating ? Color.accent : root.barForeground
          SequentialAnimation on opacity {
            running: root.generating
            loops: Animation.Infinite
            onRunningChanged: if (!running) animatedIcon.opacity = 1
            NumberAnimation { from: 1; to: 0.35; duration: 650; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0.35; to: 1; duration: 650; easing.type: Easing.InOutSine }
          }
        }
      }
    }
    onPressed: function(button) {
      if (button === Qt.RightButton) root.playPause()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: popup
    anchorItem: barButton
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: content
    contentWidth: fittedContentWidth(Style.space(420))
    contentHeight: fittedContentHeight(content.implicitHeight, Style.space(720))

    Column {
      id: content
      width: parent.width
      spacing: Style.space(12)
      focus: true
      Keys.onEscapePressed: root.close()
      Keys.onSpacePressed: root.execute(["toggle"])

      PanelHero {
        width: parent.width
        title: "SayIt"
        meta: root.stateLabel
        foreground: root.foreground
        fontFamily: root.fontFamily
        iconComponent: Component {
          Item {
            implicitWidth: Style.font.display
            implicitHeight: Style.font.display
            Image {
              id: headerIcon
              anchors.fill: parent
              source: "sayit.svg"
              sourceSize.width: 96
              sourceSize.height: 96
              fillMode: Image.PreserveAspectFit
              visible: false
            }
            ColorOverlay { anchors.fill: headerIcon; source: headerIcon; color: root.foreground }
          }
        }
      }
      PanelSeparator { foreground: root.foreground }
      Text {
        width: parent.width
        text: root.errorMessage || (root.snapshot.current && root.snapshot.current.error) || ""
        visible: text !== ""
        textFormat: Text.PlainText
        color: Color.urgent
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.Wrap
        maximumLineCount: 3
        elide: Text.ElideRight
      }
      Flow {
        width: parent.width
        spacing: Style.space(4)
        Button {
          text: "Read clipboard" + (root.clipboardShortcut ? " · " + root.clipboardShortcut : "")
          bordered: true
          implicitHeight: Style.space(32)
          iconText: "󰅍"
          focusable: true
          enabled: root.online
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.bodySmall
          horizontalPadding: Style.space(6)
          onClicked: root.execute(["clipboard", "--detach"])
        }
        Button {
          text: "Read selection" + (root.selectionShortcut ? " · " + root.selectionShortcut : "")
          bordered: true
          implicitHeight: Style.space(32)
          focusable: true
          enabled: root.online
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.bodySmall
          horizontalPadding: Style.space(6)
          onClicked: root.execute(["selection", "--detach"])
        }
        Button {
          text: "Config"
          bordered: true
          implicitHeight: Style.space(32)
          focusable: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.bodySmall
          horizontalPadding: Style.space(6)
          onClicked: { Quickshell.execDetached(["sayit", "ui", "--settings"]); root.close() }
        }
      }
      PanelSeparator { foreground: root.foreground }
      Text { text: "Recent readings"; color: root.foreground; opacity: 0.65; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
      Column {
        width: parent.width
        spacing: Style.space(4)
        Repeater {
          model: root.history
          CursorSurface {
            id: historyRow
            required property var modelData
            readonly property bool currentReading: !!root.snapshot.current && root.snapshot.current.id === modelData.id && root.busy
            // Match Obsidian's todo rows: extend the hover paint outwards,
            // then inset the contents back onto the panel's content edge.
            x: -root.rowHoverOverflow
            width: content.width + root.rowHoverOverflow * 2
            implicitHeight: Math.max(playIcon.implicitHeight, readingLabel.implicitHeight) + Style.space(8)
            foreground: root.foreground
            hasCursor: rowMouse.containsMouse || activeFocus
            activeFocusOnTab: true
            function activate() { currentReading ? root.playPause() : root.execute(["replay", modelData.id]) }
            Keys.onReturnPressed: activate()
            Keys.onEnterPressed: activate()
            Keys.onSpacePressed: activate()
            Accessible.role: Accessible.Button
            Accessible.name: (currentReading && root.playing ? "Pause: " : "Play: ") + modelData.text
            MouseArea {
              id: rowMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: historyRow.activate()
            }
            Text {
              id: playIcon
              anchors.left: parent.left
              anchors.leftMargin: root.rowHoverOverflow
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(18)
              text: historyRow.currentReading && root.playing ? "󰏤" : "󰐊"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
            Text {
              id: readingLabel
              anchors.left: playIcon.right
              anchors.leftMargin: Style.space(10)
              anchors.right: parent.right
              anchors.rightMargin: root.rowHoverOverflow + Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              text: String(historyRow.modelData.text || "").replace(/\s+/g, " ")
              textFormat: Text.PlainText
              elide: Text.ElideRight
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
          }
        }
      }
      Text {
        visible: root.history.length === 0
        text: "Your readings will appear here."
        color: root.foreground
        opacity: 0.5
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Button {
        visible: !root.online
        text: "Start service"
        focusable: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.bodySmall
        onClicked: Quickshell.execDetached(["systemctl", "--user", "start", "sayit.service"])
      }
    }
  }
}
