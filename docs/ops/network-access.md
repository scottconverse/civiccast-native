# Station network access

CivicCast keeps its application listener on a loopback address. The default is
`127.0.0.1:8000`, which is reachable only from the station computer. Do not bind
the application directly to a LAN or public interface. Remote HTTPS access is
provided by Caddy in front of that loopback listener.

## Configure the station

Open **Setup → Network Settings** as a setup admin. The support admin role can
read these settings but cannot change them.

Choose **Caddy HTTPS reverse proxy** and enter:

- The public HTTPS origin, such as `https://watch.example.gov`.
- A different staff hostname, such as `staff.example.gov`.
- The IPv4 and/or IPv6 CIDRs from which operators may reach the staff hostname.
- The loopback address and port CivicCast will listen on. Only `127.0.0.1` or
  `::1` are accepted.

Save the settings, download the generated `Caddyfile`, and review it before
deploying. Saving does not open a firewall port, change the running listener,
or start Caddy. Restart the CivicCast service to apply a changed listener or
public URL. The settings screen shows the exact generated Caddy configuration
for the saved values.

The application trusts forwarded request headers only from the selected
loopback address. The generated Caddyfile replaces `X-Forwarded-For`,
`X-Forwarded-Proto`, and `X-Forwarded-Host`, and removes the standardized
`Forwarded` header. Keep Caddy directly reachable by clients. Do not put a CDN
or another proxy in front of it unless that topology is separately configured
and verified; otherwise Caddy sees the intermediary address and the staff
network restriction will not mean what the operator expects.

## DNS, HTTPS, and Caddy

Point both DNS names to the station's Internet-facing edge. Caddy's automatic
HTTPS requires that its challenge can reach the station; allow inbound TCP 80
and 443 to Caddy only if the station's network policy permits it. Keep the
CivicCast loopback port closed to LAN and Internet traffic.

Download the Windows build from [Caddy's official download page](https://caddyserver.com/download)
and place `caddy.exe` and the downloaded `Caddyfile` in a dedicated folder.
On the station computer, open PowerShell in that folder, validate the file and
run Caddy with it:

```powershell
.\caddy.exe validate --config .\Caddyfile
.\caddy.exe run --config .\Caddyfile
```

That foreground command ends when its process stops. For unattended operation,
install it as a Windows service using [Caddy's Windows service instructions](https://caddyserver.com/docs/running#windows-service).
Use an absolute `--config` path in the service command, set automatic startup,
and give the selected service account read access to the executable/configuration
and write access to its certificate-storage folder. This Caddy service is
separate from `CivicCastSupervisor`; CivicCast does not install it automatically.
Confirm it starts after a reboot with the same configuration. Review the DNS,
CIDR, and route settings below before exposing it.

## What each hostname exposes

The public hostname forwards only resident pages, static assets, the public
API, and public media paths. Other paths return 404. It does not forward the
operator console or `/api/staff/*`.

The separate staff hostname forwards to CivicCast only when the connecting
client address matches one of the configured staff CIDRs. CivicCast bearer
authentication and role checks still apply. First Setup (`/api/setup/*`) is
explicitly blocked by the proxy and remains available only from the station
computer. This is necessary because Caddy connects to the app over loopback,
which would otherwise make a proxied request appear local to the app.

The resident site is the staff hostname's default page. To sign in to the
operator console, open the exact URL
`https://staff.example.gov/operator/#/login`, replacing the hostname with the
configured staff hostname.

## Verify from both sides

From a public network, confirm the public hostname serves the resident portal
and public media. Confirm `/operator/`, `/api/staff/`, and `/api/setup/` do not
reach the application on the public hostname. From a client inside an approved
staff CIDR, open `https://staff.example.gov/operator/#/login` (using the
configured staff hostname) and sign in with an operator account.
From a client outside the approved CIDRs, the staff hostname must return the
network restriction response before CivicCast is reached.

If remote staff access fails, first check the source address seen by Caddy and
the configured CIDR. Do not widen the list to `0.0.0.0/0` or `::/0`. If only
local access is needed, return the mode to **This computer only** and restart
the CivicCast service.
