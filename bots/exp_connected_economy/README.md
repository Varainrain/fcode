# Connected Economy experiment

**Rejected.** On production engine 2.3.3 the broad rewrite failed the first
12-game parent crash screen at 3-9 (25%), with core kills 3-9. It changed the
opening routing surface too much. Preserve this folder as evidence; the next
experiment must leave all pre-round-80 parent routing unchanged and add only a
late orphan-chain repair.

Parent: frozen `meta-generalist-v1`, which the user reports is on the live
ladder. The parent source and ZIP hashes matched `meta_generalist_v1_results.json`
before this folder was created.

## Observed general failure

Long games can contain many conveyors while one or more harvesters never feed
the core. The parent counts any adjacent friendly conveyor as a harvester
connection, treats any visible conveyor as a routing sink without following its
facing, and disables all route completion at round 40. Defensive wall conveyors
can therefore hide orphan harvesters or attract economic paths into dead ends.

In the three latest local parent-line smoke replays, one of three harvesters was
still unserved at the round-40 transition and remained unserved at game end
despite 18-23 living conveyors.

## Independent mechanism

- Remember observed friendly conveyor facings and remove observations when a
  tile is revisited without that conveyor.
- Prove core-connected conveyors by following actual output directions to the
  core in a fixed point. Unknown, wrong-facing, cyclic, and dead-end components
  are not merge targets.
- A harvester is served only by an adjacent chain root whose output points away
  from it and whose chain is proven connected.
- Extend the actual output of orphan chains; fresh links route only to the core
  or a proven connected trunk.
- Preserve the round-40 economy-to-pressure transition. From round 80, allow
  one locally nearest builder to spend otherwise sub-siege reserves on a
  bounded repair of an already-built harvester/chain, at no more than the
  parent's original route priority. Do not discover new ore or start broad
  economic expansion.
- Do not use map names, dimensions, opponent identity, or store protocol
  changes. Root sources and the active package remain unchanged.

## Acceptance evidence

Deterministic tests must cover connected trunks, wrong-facing adjacency,
disconnected merge rejection, cycles, stale-observation cleanup, dead-end
extension, and the cutoff boundary. Replay audits must show fewer unserved
harvesters/disconnected conveyors. Graduated gates must preserve core-kill
pressure against the frozen parent, `spar_rush`, and unrelated bot families;
promotion requires a multi-opponent gain, not one long map.
