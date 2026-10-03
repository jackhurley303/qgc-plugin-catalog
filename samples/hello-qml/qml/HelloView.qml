import QtQuick
import QtQuick.Layouts

import QGroundControl.PluginUI

Rectangle {
    color: "#2c2c2c"

    ColumnLayout {
        anchors.centerIn: parent
        spacing:          10

        QGCLabel {
            text:             "Hello QML"
            font.pointSize:   24
            font.bold:        true
            color:            "#ffffff"
            Layout.alignment: Qt.AlignHCenter
        }

        QGCLabel {
            text:             "This page comes from a qml-tier plugin installed from the catalog."
            color:            "#ffffff"
            Layout.alignment: Qt.AlignHCenter
        }
    }
}
