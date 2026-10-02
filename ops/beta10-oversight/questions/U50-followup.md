# U50 follow-up (coordinator, 14:58) - verify-09 of rung 8h-post-u47 with your keep dir live

Good: span 60.0 s on all three channels, from_keep 25 + from_live 5, cues 10/7/13, heartbeat 3.5 s.
Defect: on every channel the 5 `from_live` segments are UNVERIFIED "segment could not be copied out of the live window
(copy race)" - the relay rotates them away before the verify reaches them (it keeps ~7). So every verify reads
UNVERIFIED instead of PASS. Fix: prefer the KEEP copy for any segment present in the keep dir; take a segment from
live only if the keeper does not have it; if a live copy races, fall back to the keep copy by name at that moment
(re-check the keep dir), and only then UNVERIFIED. Prove: a verify on the live station shows caption_decode_back
PASS (0 unverified) on all three with span 60 s. Same delivery rules (atomic, running rung).
