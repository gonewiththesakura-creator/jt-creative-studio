# Initial transport failure

Panel job `59dbb0fa3b9a` terminated in 0.6 seconds with `[Errno 104] Connection reset by peer` on 2026-09-17 at 06:22:42 UTC. No image was returned.

The workstation's persistent admission fence remained `{}` with last-write timestamp **2026-09-14T23:46:18.4015137Z**, older than this attempt. The proxy must durably write this fence before creating its upstream worker. Therefore this attempt did not enter the paid upstream worker on this workstation. Its replacement SSH tunnel process started at **2026-09-17T06:22:45.490132Z**, immediately after the connection failure.

Read-only checks and invalid-payload probes subsequently confirmed the candidate used the expected loopback URL, no proxy environment variables, and the tunnel returned HTTP 400 for an invalid request without creating an upstream worker. This is transport evidence, not a statement about model availability.

The failed candidate was stopped and removed after archiving its sanitized public job result. A fresh candidate will perform the one authorized upstream image test with the same request structure. No automatic paid retry or alternate model probing is permitted.
