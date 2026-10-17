import Gio from "gi://Gio";
import {Extension} from "resource:///org/gnome/shell/extensions/extension.js";

const BUS_NAME = "org.focusos.Focus";
const OBJECT_PATH = "/org/focusos/Focus";
const INTERFACE_XML = `
<node>
  <interface name="org.focusos.Focus">
    <method name="GetActiveWindow">
      <arg name="window" type="s" direction="out"/>
    </method>
  </interface>
</node>`;

export default class FocusOSActiveWindowExtension extends Extension {
    enable() {
        this._activeWindowService = {
            GetActiveWindow() {
                const window = global.display.get_focus_window();
                const pid = window?.get_pid() ?? 0;
                return JSON.stringify({
                    pid: pid > 0 ? pid : null,
                    application: window?.get_wm_class() ?? null,
                    title: window?.get_title() ?? null,
                    warning: null,
                });
            },
        };

        this._dbusObject = Gio.DBusExportedObject.wrapJSObject(
            INTERFACE_XML,
            this._activeWindowService,
        );
        this._busOwner = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            connection => this._dbusObject.export(connection, OBJECT_PATH),
            null,
            null,
        );
    }

    disable() {
        if (this._busOwner) {
            Gio.bus_unown_name(this._busOwner);
            this._busOwner = null;
        }
        this._dbusObject?.unexport();
        this._dbusObject = null;
        this._activeWindowService = null;
    }
}
