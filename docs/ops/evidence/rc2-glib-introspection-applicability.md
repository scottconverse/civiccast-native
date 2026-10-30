# GLib 2.88.4: CVE-2026-58016 applicability

Reviewed October 30, 2026 for the Windows RC2 application paths. This is an
application reachability assessment, not a claim that GLib 2.88.4 contains the
upstream fix.

The upstream change is confined to `g_dbus_node_info_new_for_xml`'s D-Bus
introspection XML parser. Incorrectly nested `node` elements are the trigger:
<https://github.com/GNOME/glib/commit/c9da977c178fbfc0e4caf99f9fdf5dc433d6fcc2>.
The reviewed upstream 2.88.4 source retains the earlier condition. The shipped
GIO DLL also remains present; absence of the library is not the justification.

The Windows application does not accept or parse D-Bus introspection XML.
Review of CivicCast's Python/Rust application sources found no GDBus or
`g_dbus_node_info_new_for_xml` call. Its native worker constructs the approved
GStreamer graphs and receives typed pipe commands, not arbitrary Python or
introspection XML. Uploaded media, caption text, agenda XML and HTTP inputs are
not passed to this GDBus parser. GStreamer factory selection remains bounded by
`civiccast/native/runtime_closure.py`; no new factories are enabled here.

A PE import-table check of all 117 DLL/PYD/EXE files in the preserved, verified
246-file GStreamer closure found no importer of
`g_dbus_node_info_new_for_xml`. The tree was the signed RC1 dependency tree
under candidate `6571f84186ea5a9373be31f92b8f3fb883fa3863`, reused unchanged by
RC2. This corroborates the application source review; an import-table check
alone cannot exclude internal or dynamically resolved calls. GLib's callable
API and internal D-Bus functionality are not being declared removed.

Disposition: not reachable through the shipped Windows application's input
paths. Triage binds only `gstreamer-glib` 2.88.4 and this CVE, expires November
29, 2026, and must be revisited if D-Bus/introspection handling, native graph
capabilities or dependency identity changes. No package upgrade, parser guard
removal, scan suppression for other findings or runtime rebuild was performed.
