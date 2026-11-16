#!/usr/bin/env python3
"""Minimal org.freedesktop.systemd1 D-Bus shim backed by systemctl3.py.

Satisfies unifi-core (dbus-next) and uos-agent (zbus) D-Bus queries in
cgroups-v2 / non-PID1 systemd containers where systemd D-Bus is absent.
"""

import re
import subprocess
from pathlib import Path
from typing import Dict, Tuple

import dbus  # type: ignore[import-not-found]
import dbus.mainloop.glib  # type: ignore[import-not-found]
import dbus.service  # type: ignore[import-not-found]
from gi.repository import GLib  # type: ignore[import-not-found]

SYSTEMD_BUS_NAME = "org.freedesktop.systemd1"
MANAGER_PATH = "/org/freedesktop/systemd1"
UNIT_PREFIX = "/org/freedesktop/systemd1/unit/"
MANAGER_IFACE = "org.freedesktop.systemd1.Manager"
UNIT_IFACE = "org.freedesktop.systemd1.Unit"
SERVICE_IFACE = "org.freedesktop.systemd1.Service"
PROPS_IFACE = "org.freedesktop.DBus.Properties"


def escape_unit_name(name: str) -> str:
    """Escape a systemd unit name to a valid D-Bus object path segment."""
    out = []
    for ch in name:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append(f"_{ord(ch):02x}")
    return "".join(out)


def normalize_unit(name: str) -> str:
    name = name.strip()
    if "." not in name:
        name = f"{name}.service"
    return name


def read_unit_state(unit: str) -> Tuple[str, str, str]:
    """Return (load_state, active_state, sub_state) for a unit without subprocess overhead."""
    status_file = Path(f"/run/{unit}.status")
    active = "inactive"
    if status_file.is_file():
        try:
            text = status_file.read_text(encoding="utf-8", errors="ignore")
            m_state = re.search(r"ActiveState\s*=\s*(\S+)", text)
            m_pid = re.search(r"MainPID\s*=\s*(\d+)", text)
            if m_pid:
                pid = int(m_pid.group(1))
                stat_path = Path(f"/proc/{pid}/stat")
                if pid > 0 and stat_path.is_file():
                    stat_txt = stat_path.read_text(encoding="utf-8", errors="ignore")
                    rparen = stat_txt.rfind(")")
                    proc_state = stat_txt[rparen + 2 : rparen + 3] if rparen != -1 else ""
                    if proc_state and proc_state != "Z":
                        active = "active"
            if active != "active" and m_state:
                active = m_state.group(1).strip()
        except OSError:
            pass

    if active == "active":
        sub = "running"
    elif active == "failed":
        sub = "failed"
    else:
        sub = "dead"

    load_state = "loaded"
    for base in (Path("/etc/systemd/system"), Path("/usr/lib/systemd/system"), Path("/lib/systemd/system")):
        if (base / unit).exists():
            break
    else:
        if "@" in unit:
            tmpl = re.sub(r"@[^.]+\.", "@.", unit)
            if any((b / tmpl).exists() for b in (Path("/etc/systemd/system"), Path("/usr/lib/systemd/system"), Path("/lib/systemd/system"))):
                load_state = "loaded"
            else:
                load_state = "not-found"
        else:
            load_state = "not-found"

    return load_state, active, sub


class UnitObject(dbus.service.Object):
    def __init__(self, bus_name: dbus.service.BusName, object_path: str, unit_name: str):
        super().__init__(bus_name, object_path)
        self.unit_name = unit_name
        _, self.last_active, _ = read_unit_state(unit_name)

    def _props_for(self, interface_name: str) -> Dict[str, object]:
        load_state, active_state, sub_state = read_unit_state(self.unit_name)
        unit_props = {
            "Id": dbus.String(self.unit_name),
            "LoadState": dbus.String(load_state),
            "ActiveState": dbus.String(active_state),
            "SubState": dbus.String(sub_state),
            "StartLimitBurst": dbus.UInt32(5),
            "StartLimitIntervalUSec": dbus.UInt64(10_000_000),
        }
        service_props = {
            "Result": dbus.String("success" if active_state != "failed" else "exit-code"),
            "StatusText": dbus.String(""),
            "ExecMainStartTimestampMonotonic": dbus.UInt64(1),
        }
        if interface_name == UNIT_IFACE:
            return unit_props
        if interface_name == SERVICE_IFACE:
            return service_props
        if interface_name == "":
            merged = dict(unit_props)
            merged.update(service_props)
            return merged
        return {}

    def poll_and_emit(self) -> None:
        _, active_state, sub_state = read_unit_state(self.unit_name)
        if active_state != self.last_active:
            self.last_active = active_state
            self.PropertiesChanged(
                UNIT_IFACE,
                dbus.Dictionary(
                    {
                        "ActiveState": dbus.String(active_state),
                        "SubState": dbus.String(sub_state),
                    },
                    signature="sv",
                ),
                dbus.Array([], signature="s"),
            )

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface_name: str, property_name: str):
        props = self._props_for(interface_name)
        if property_name in props:
            return props[property_name]
        # Fallback check across both interfaces
        all_props = self._props_for("")
        if property_name in all_props:
            return all_props[property_name]
        return dbus.String("")

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface_name: str):
        return dbus.Dictionary(self._props_for(interface_name), signature="sv")

    @dbus.service.signal(PROPS_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface_name: str, changed_properties, invalidated_properties):
        pass

    @dbus.service.method(UNIT_IFACE, in_signature="s", out_signature="o")
    def Start(self, mode: str):
        subprocess.Popen(["/usr/bin/systemctl", "start", self.unit_name])
        return dbus.ObjectPath("/org/freedesktop/systemd1/job/1")

    @dbus.service.method(UNIT_IFACE, in_signature="s", out_signature="o")
    def Stop(self, mode: str):
        subprocess.Popen(["/usr/bin/systemctl", "stop", self.unit_name])
        return dbus.ObjectPath("/org/freedesktop/systemd1/job/1")

    @dbus.service.method(UNIT_IFACE, in_signature="s", out_signature="o")
    def Restart(self, mode: str):
        subprocess.Popen(["/usr/bin/systemctl", "restart", self.unit_name])
        return dbus.ObjectPath("/org/freedesktop/systemd1/job/1")

    @dbus.service.method(SERVICE_IFACE, in_signature="", out_signature="a(uss)")
    def GetProcesses(self):
        return dbus.Array([], signature="(uss)")


class SystemdManager(dbus.service.Object):
    def __init__(self, bus_name: dbus.service.BusName):
        super().__init__(bus_name, MANAGER_PATH)
        self.bus_name = bus_name
        self.units: Dict[str, UnitObject] = {}
        self.job_counter = 1

    def _ensure_unit(self, name: str) -> dbus.ObjectPath:
        unit = normalize_unit(name)
        path = f"{UNIT_PREFIX}{escape_unit_name(unit)}"
        if unit not in self.units:
            self.units[unit] = UnitObject(self.bus_name, path, unit)
        return dbus.ObjectPath(path)

    def _next_job(self) -> dbus.ObjectPath:
        self.job_counter += 1
        return dbus.ObjectPath(f"/org/freedesktop/systemd1/job/{self.job_counter}")

    @dbus.service.method(MANAGER_IFACE, in_signature="", out_signature="")
    def Subscribe(self):
        return None

    @dbus.service.method(MANAGER_IFACE, in_signature="", out_signature="")
    def Unsubscribe(self):
        return None

    @dbus.service.method(MANAGER_IFACE, in_signature="s", out_signature="o")
    def LoadUnit(self, name: str):
        return self._ensure_unit(name)

    @dbus.service.method(MANAGER_IFACE, in_signature="s", out_signature="o")
    def GetUnit(self, name: str):
        return self._ensure_unit(name)

    @dbus.service.method(MANAGER_IFACE, in_signature="ss", out_signature="o")
    def StartUnit(self, name: str, mode: str):
        unit = normalize_unit(name)
        subprocess.Popen(["/usr/bin/systemctl", "start", unit])
        return self._next_job()

    @dbus.service.method(MANAGER_IFACE, in_signature="ss", out_signature="o")
    def StopUnit(self, name: str, mode: str):
        unit = normalize_unit(name)
        subprocess.Popen(["/usr/bin/systemctl", "stop", unit])
        return self._next_job()

    @dbus.service.method(MANAGER_IFACE, in_signature="ss", out_signature="o")
    def RestartUnit(self, name: str, mode: str):
        unit = normalize_unit(name)
        subprocess.Popen(["/usr/bin/systemctl", "restart", unit])
        return self._next_job()

    @dbus.service.method(MANAGER_IFACE, in_signature="ss", out_signature="o")
    def ReloadUnit(self, name: str, mode: str):
        unit = normalize_unit(name)
        subprocess.Popen(["/usr/bin/systemctl", "reload", unit])
        return self._next_job()

    @dbus.service.method(MANAGER_IFACE, in_signature="s", out_signature="")
    def ResetFailedUnit(self, name: str):
        return None

    @dbus.service.signal(MANAGER_IFACE, signature="")
    def UnitFilesChanged(self):
        pass

    def poll_units(self) -> bool:
        for unit_obj in list(self.units.values()):
            try:
                unit_obj.poll_and_emit()
            except Exception:
                pass
        return True


def main() -> None:
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    bus_name = dbus.service.BusName(SYSTEMD_BUS_NAME, bus)
    manager = SystemdManager(bus_name)
    GLib.timeout_add_seconds(2, manager.poll_units)
    loop = GLib.MainLoop()
    loop.run()


if __name__ == "__main__":
    main()
