# UniFi OS Server — Home Assistant App Documentation

## Overview
This app runs **UniFi OS Server 6+** and **UniFi Network Application 11+** on Home Assistant OS. It replaces the end-of-life legacy UniFi Network Application add-on (`a0d7b954_unifi`).

## Configuration

```yaml
system_ip: "192.168.1.10"
log_level: "info"
memory_init: 512
memory_max: 1536
show_journal: false
```

- **`system_ip` (Required):** Set this to the LAN IPv4 address of your Home Assistant host so UniFi devices know where to send inform packets (`http://<system_ip>:8080/inform`).
- **`memory_init` / `memory_max`:** Initial and maximum JVM heap size (in MB) for the UniFi Network Application.
- **`show_journal`:** Forward internal service logs to the Home Assistant add-on log viewer.

## Migrating from the Legacy UniFi Network Add-on

1. In your existing UniFi Network add-on (`https://<HA-IP>:8443`), download a backup (`.unf`) via **Settings > System > Backups**.
2. Stop the legacy **UniFi Network Application** add-on and disable **Start on boot**.
3. Configure `system_ip` in **UniFi OS Server** and start the app.
4. Open `https://<HA-IP>:11443`, complete initial setup, and select **Restore from Backup** using your `.unf` file.
5. In UniFi OS **Control Plane > Admins**, create a local-only admin account for Home Assistant, then update the Home Assistant **UniFi Network** integration port from `8443` to `11443`.
