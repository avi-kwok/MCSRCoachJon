# Bastion route library

Reference routes from VODs you trust (top runners, guides). The coach may cite one by id in a tip's
`reference_route`; the UI then plays it side by side with your run. Entries marked `status: example`
are ignored (not sent to the coach, not served).

Format — one entry per route: a `## <id>` heading (kebab-case, unique), then `key: value` lines:
- `type:` housing | treasure | bridge | stables (required)
- `entry:` where/which side you enter, e.g. "front gate", "left side from lava", "top" (required)
- `url:` YouTube link — watch?v=, youtu.be/ or shorts/ (required)
- `start:` m:ss where the route starts in that video (required); `end:` m:ss (optional)
- `runner:`, `time:` (route time if known, e.g. 0:45), `notes:`, `status:` (draft | confirmed | example) — optional

## example-housing-front
status: example
type: housing
entry: front gate (side facing the bridge)
url: https://www.youtube.com/watch?v=XXXXXXXXXXX
start: 1:23
end: 2:05
runner: (runner name)
time: 0:42
notes: Placeholder showing the format — replace with a real VOD, then delete this entry.

## bridge-chalice-left-dk
status: draft
type: bridge
entry: chalice start
url: https://youtu.be/3W5CXyTneqc
start: 0:00
runner: doogile (route author)
notes: Left DK. Start timestamp not yet refined. See knowledge/bridge_routes.md for when to play it.

## bridge-chalice-cs
status: draft
type: bridge
entry: chalice start
url: https://youtu.be/U10R9NG2-1A
start: 0:00
notes: CS (cracksmoker). Start timestamp not yet refined.

## bridge-chalice-soog
status: draft
type: bridge
entry: chalice start
url: https://youtu.be/zmwEKNFg2Gk
start: 0:00
runner: silver/doogile
notes: Silver/doog right DK (soog). Start timestamp not yet refined.

## bridge-chalice-left-dk-to-cs
status: draft
type: bridge
entry: chalice start
url: https://youtu.be/Dm_wqJIa-NE
start: 0:00
notes: Left DK -> CS (after checking the left rampart and finding a single). Start timestamp not yet refined.

## bridge-chalice-left-dk-flammable
status: draft
type: bridge
entry: chalice start
url: https://youtu.be/vJDpzFwkSp8
start: 0:00
notes: Left DK with leaves/wood. Use when the only building blocks are flammable (leaves/wood). Start timestamp not yet refined.

## bridge-chalice-right-dk-flammable
status: draft
type: bridge
entry: chalice start
url: https://youtu.be/Lfajg8WPZGw
start: 0:00
notes: Right DK with leaves/wood. Use when the only building blocks are flammable (leaves/wood). Start timestamp not yet refined.
