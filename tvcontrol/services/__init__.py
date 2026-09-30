import os

UID = os.getuid()
ENV = os.environ.copy()
ENV["XDG_RUNTIME_DIR"] = f"/run/user/{UID}"
if "DISPLAY" not in ENV:
    ENV["DISPLAY"] = ":0"

if "DBUS_SESSION_BUS_ADDRESS" not in ENV:
    dbus_socket = f"/run/user/{UID}/bus"
    if os.path.exists(dbus_socket):
        ENV["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_socket}"

for s_path in [os.environ.get("YDOTOOL_SOCKET"), "/tmp/.ydotool_socket", f"/run/user/{UID}/.ydotool_socket"]:
    if s_path and os.path.exists(s_path):
        ENV["YDOTOOL_SOCKET"] = s_path
        break
else:
    ENV["YDOTOOL_SOCKET"] = "/tmp/.ydotool_socket"
