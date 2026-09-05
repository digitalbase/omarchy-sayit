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
          color: root.busy ? Color.accent : root.barForeground
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

      Row {
        width: parent.width
        spacing: Style.space(10)
        Text {
          text: "SayIt"
          width: parent.width - statusText.implicitWidth - parent.spacing
          color: root.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.title
          font.bold: true
        }
        Text {
          id: statusText
          text: root.stateLabel
          color: root.foreground
          opacity: 0.65
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          anchors.verticalCenter: parent.verticalCenter
        }
      }
      PanelSeparator { foreground: root.foreground }
      Text {
        width: parent.width
        text: root.errorMessage || (root.snapshot.current && root.snapshot.current.error) || ""
        visible: text !== ""
        textFormat: Text.PlainText
        color: Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.Wrap
        maximumLineCount: 3
        elide: Text.ElideRight
      }
      Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Style.space(8)
        Button { text: "Read clipboard"; iconText: "󰅍"; bordered: true; focusable: true; enabled: root.online; onClicked: root.execute(["clipboard", "--detach"]) }
        Button { text: "Read selection"; focusable: true; enabled: root.online; onClicked: root.execute(["selection", "--detach"]) }
      }
      PanelSeparator { foreground: root.foreground }
      Text { text: "Recent readings"; color: root.foreground; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.caption }
      Repeater {
        model: root.history
        Button {
          required property var modelData
          width: content.width
          id: historyButton
          readonly property bool currentReading: !!root.snapshot.current && root.snapshot.current.id === modelData.id && root.busy
          iconText: currentReading && root.playing ? "󰏤" : "󰐊"
          tooltipText: currentReading ? (root.playing ? "Pause reading" : "Resume reading") : "Play reading"
          leftAlign: true
          focusable: true
          fontSize: Style.font.bodySmall
          onClicked: currentReading ? root.playPause() : root.execute(["replay", modelData.id])
          Text {
            anchors.left: parent.left
            anchors.leftMargin: Style.space(32)
            anchors.right: parent.right
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            text: String(historyButton.modelData.text || "").replace(/\s+/g, " ")
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }
        }
      }
      Text {
        visible: root.history.length === 0
        text: "Your readings will appear here."
        color: root.foreground
        opacity: 0.5
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
      PanelSeparator { foreground: root.foreground }
      Row {
        width: parent.width
        spacing: Style.space(8)
        Button { text: "Models, voices & history"; focusable: true; onClicked: { Quickshell.execDetached(["sayit", "ui"]); root.close() } }
        Button { visible: !root.online; text: "Start service"; focusable: true; onClicked: Quickshell.execDetached(["systemctl", "--user", "start", "sayit.service"]) }
      }
    }
  }
}
