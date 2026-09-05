import QtQuick
import QtQuick.Controls as Controls
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
  readonly property string readingText: {
    var job = snapshot.current
    if (!job) return "Select text and press F10, or copy it and choose Read clipboard."
    var segments = job.segments || []
    for (var i = 0; i < segments.length; i++) {
      var segment = segments[i]
      if (snapshot.position >= segment.start && snapshot.position < segment.start + segment.duration)
        return segment.text
    }
    return job.text || ""
  }
  implicitWidth: barRow.implicitWidth
  implicitHeight: barRow.implicitHeight

  function clock(seconds) {
    var value = Math.max(0, Math.floor(Number(seconds) || 0))
    return Math.floor(value / 60) + ":" + String(value % 60).padStart(2, "0")
  }
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

  Row {
    id: barRow
    BarIconButton {
      id: barButton
      bar: root.bar
      text: "󰕾"
      active: root.busy
      tooltipText: "SayIt · " + root.stateLabel + "\nClick to open · Right-click to pause/resume"
      onPressed: function(button) {
        if (button === Qt.RightButton) root.playPause()
        else root.toggle()
      }
    }
    BarIconButton {
      bar: root.bar
      visible: root.busy && !(root.bar && root.bar.vertical)
      text: root.playing ? "󰏤" : "󰐊"
      tooltipText: root.playing ? "Pause speech" : "Resume speech"
      onPressed: root.execute(["toggle"])
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
      Text {
        width: parent.width
        text: root.readingText
        textFormat: Text.PlainText
        color: root.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        wrapMode: Text.Wrap
        maximumLineCount: 6
        elide: Text.ElideRight
        lineHeight: 1.25
      }
      Controls.Slider {
        width: parent.width
        from: 0
        to: Math.max(1, root.snapshot.duration || 0)
        value: root.snapshot.position || 0
        enabled: root.busy && root.snapshot.duration > 0
        id: timeline
        implicitHeight: Style.space(22)
        implicitWidth: Style.space(200)
        background: Rectangle {
          x: timeline.leftPadding
          y: timeline.topPadding + timeline.availableHeight / 2 - height / 2
          width: timeline.availableWidth
          height: Style.space(3)
          radius: height / 2
          color: Qt.alpha(root.foreground, 0.18)
          Rectangle { width: parent.width * timeline.visualPosition; height: parent.height; radius: parent.radius; color: Color.accent }
        }
        handle: Rectangle {
          x: timeline.leftPadding + timeline.visualPosition * (timeline.availableWidth - width)
          y: timeline.topPadding + timeline.availableHeight / 2 - height / 2
          width: Style.space(10); height: width; radius: width / 2
          color: Color.accent
        }
        onMoved: seekDelay.restart()
        Timer {
          id: seekDelay
          interval: 180
          onTriggered: root.execute(["seek", String(parent.value)])
        }
        Accessible.name: "Speech position"
      }
      Row {
        width: parent.width
        Text {
          width: parent.width - speedRow.implicitWidth
          text: root.clock(root.snapshot.position) + " / " + root.clock(root.snapshot.duration)
          color: root.foreground
          opacity: 0.65
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          anchors.verticalCenter: parent.verticalCenter
        }
        Row {
          id: speedRow
          spacing: Style.space(2)
          Button { text: "−"; tooltipText: "Slower"; focusable: true; onClicked: root.execute(["rate", String(Math.max(0.5, Number(root.snapshot.rate || 1) - 0.1))]) }
          Text { text: Number(root.snapshot.rate || 1).toFixed(1) + "×"; color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall; anchors.verticalCenter: parent.verticalCenter }
          Button { text: "+"; tooltipText: "Faster"; focusable: true; onClicked: root.execute(["rate", String(Math.min(2, Number(root.snapshot.rate || 1) + 0.1))]) }
        }
      }
      Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Style.space(12)
        Button { iconText: "󰑟"; text: "10s"; tooltipText: "Back ten seconds"; focusable: true; enabled: root.busy; onClicked: root.execute(["skip", "-10"]) }
        Button { iconText: root.playing ? "󰏤" : "󰐊"; text: root.playing ? "Pause" : root.busy ? "Resume" : "Play again"; bordered: true; focusable: true; enabled: root.busy || !!(root.snapshot.current && root.snapshot.current.audio); onClicked: root.playPause() }
        Button { iconText: "󰓛"; text: "Stop"; focusable: true; enabled: root.busy; onClicked: root.execute(["stop"]) }
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
          iconText: "󰐊"
          tooltipText: "Replay reading"
          leftAlign: true
          focusable: true
          fontSize: Style.font.bodySmall
          onClicked: root.execute(["replay", modelData.id])
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
