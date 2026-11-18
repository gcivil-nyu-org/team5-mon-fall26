# Stories

One file per user story, mirroring the ZenHub issue (story line, developer tasks, acceptance criteria).

- `US1.md` to `US9.md` are Epic 1 issues #3 to #11. `../epic-1.md` is issue #1.
- Generate or refresh them from GitHub with `bash scripts/sync-stories.sh` (needs the GitHub CLI).
- ZenHub/GitHub is the source of truth for wording and estimates. If a story changes there, run the script again.
- US0 (#16, data import) is split into `US0a.md` (#20) and `US0b.md` (#21).

| File | Issue | Story |
|---|---|---|
| US0a.md | #20 | Import TLC trips and build stats tables |
| US0b.md | #21 | Taxi zone shapes |
| US1.md | #3 | View Taxi Demand Map |
| US2.md | #4 | Select Trip Zones |
| US3.md | #5 | View Demand Heatmap |
| US4.md | #6 | Filter by Time |
| US5.md | #7 | View Fare Range |
| US6.md | #8 | View Trip Duration |
| US7.md | #9 | Find Best and Worst Travel Times |
| US8.md | #10 | View Trip Summary |
| US9.md | #11 | Use Without an Account |
| US27.md | #74 | Import Rideshare Trip Statistics (split into #82 to #85; written by hand, not by the sync script) |
| US28.md | #75 | Compare Taxi and Rideshare Fares for My Trip (written by hand, not by the sync script) |
| US29.md | #76 | Surge-Pricing Overlay (written by hand, not by the sync script) |
| US30.md | #92 | Choose a Display Name (written by hand, not by the sync script) |
| US31.md | #93 | Post a Ride-Share Offer (written by hand, not by the sync script) |
| US32.md | #94 | Find Shared Rides on My Route (written by hand, not by the sync script) |
| US33.md | #95 | Show Interest in a Shared Ride (written by hand, not by the sync script) |
| US34.md | #96 | Accept or Decline Interested Riders (written by hand, not by the sync script) |
| US35.md | #97 | Edit, Close, or Delete My Post (written by hand, not by the sync script) |
| US36.md | #98 | Message Riders About a Shared Ride (written by hand, not by the sync script) |
| US37.md | #99 | My Rides (written by hand, not by the sync script) |
| US38.md | #101 | Report a Post or Message (written by hand, not by the sync script) |
| US39.md | #113 | Admin Access and Staff Accounts (copied with `gh issue view`, not by the sync script) |
