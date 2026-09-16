# Forecasting the next node: method

Read this before running `helpers/node_forecast.py` and before writing the brief's
**Where the next node probably goes** section.

The job: name the cluster that gets the occupier's next distribution node, the zone inside
it, the size and tenure to expect, the window, and the evidence that would prove you wrong.
Not "they will need more space eventually". A ranked, dated, falsifiable forecast.

This is the section that turns a brief from a summary of public facts into something the
occupier cannot get anywhere else. It is also the easiest section in the whole document to
fake, so the rules below are about making it honest rather than making it confident.

## Why the obvious model is wrong

A model that ranks clusters by current unserved demand will pick the wrong answer almost
every time. Four reasons, and each one is a correction the tool implements.

| Failure | Correction |
|---|---|
| **It ranks the network the occupier HAS.** A cluster of markets opened this year looks trivial today and dominates in three years. The node is decided against the forward estate, because the lead time is 12 to 18 months. | Project every market forward over the occupier's actual lead time plus a year, using a growth rate calibrated from the occupier's own past market entries. |
| **It treats every demand point alike.** One node serving five adjacent markets earns five times what a node serving one dead-end market earns. | Score demand debt per market earned, and rank contiguous clusters above isolated ones. |
| **It conflates two different decisions.** A node that UNBLOCKS growth gates revenue and gets taken now. A node that REDUCES cost on an estate already scaling can wait, and usually does. Ranked together, the urgent one is buried under the large one. | The tier rule below. It is the single most useful idea in this file. |
| **It locates on demand geometry alone.** Observed node choices sit well away from the demand centroid, pulled toward the inbound gateway. | Report a landing zone across several candidate gateways and a range of pull weights, never a point. |

## The tier rule

Classify every cluster before ranking it.

**Tier 1, growth-enabling.** Early in life (inside the occupier's own early-growth window)
and effectively unserved: no existing node within one transport day. The store or depot
programme physically cannot scale on the current trunk. This gates revenue, so it is decided
on the occupier's timetable, not the property market's, and it is decided now because of the
lead time. **Tier 1 is the forecast.**

**Tier 2, cost-reducing.** Unserved, but the estate there is already scaling on the existing
trunk. It demonstrably works; it is just expensive. A cost case waits for a budget cycle, a
lease event or a new finance director. Real, and usually second.

**Tier 3, partly served.** An existing node already reaches part of it. A new node trims
cost and unblocks nothing.

The test that separates tier 1 from tier 2 is not size. It is whether the occupier's own
growth programme is blocked. A mature market with a huge trunk bill is a tier 2 even when it
is the largest number on the page: it has proved the trunk works. Say so in the brief, because
the room will point at the big number and ask why it is not first.

## The three calibrations

Every number in a forecast comes from data or it is labelled a guess. There are exactly three,
and the tool refuses to make a timing claim when the second is missing.

**1. The growth rate, from the occupier's own history.** Every past market entry is a
labelled training example: entry date against current demand points gives the rate a new
market ramps at, and the age at which that rate bends into the mature rate. Five or six past
entries is a usable curve. Never import a sector average: a chain that opens 13 a year and one
that opens 60 behave completely differently and the difference is the whole forecast.
`--calibrate` does this and prints the observed range, which is your uncertainty.

**2. The trigger, from peers.** How many demand points a comparable business runs per node.
Occupiers that have already scaled across the same geography are a real, small calibration
set: a peer with nineteen dated node openings is nineteen observations of at what size a node
gets added. Pass them in `peers.csv`.

Two cautions. The spread will be enormous, because network shape is a choice: an occupier
running few large automated nodes will show three or four times the demand points per node of
one running many manual regional nodes. Report the spread, take the median of the genuinely
comparable, and say which peer sits at each end. And weight toward peers whose **operating
model** matches: outsourced-and-automated is a different business from self-operated-and-manual,
whatever the store counts say.

**3. The location rule, back-tested on nodes the occupier has already taken.** See below. This
is the calibration most often skipped and the one that most often embarrasses.

## Locating inside the winning cluster

Three steps, in order, and the first one alone is not enough.

**Demand centroid.** Weighted by forward demand and by volume per demand point where they
differ. Necessary, and on its own it will be a few hundred km wrong.

**Pull toward the inbound gateway.** Occupiers do not site nodes at the middle of their
demand. They site them where goods arrive and then flow outward. Candidate gateways: the deep-sea
port a sector's imports actually use, an inland rail terminal, a land border crossing, or the
existing network's trunk origin. **Pass several, because which one wins is usually unknown, and
report a zone rather than a point.**

**Then filter by supply and constraint, which is not geometry at all.** Standing stock of the
right size exists in specific parks and nowhere else. Labour, power, grid queues, planning
timescales and incentives with deadlines all cut candidate plots. A geometric answer in a
sub-market with no suitable buildings is not an answer. This step needs local market knowledge
and is where an adviser adds what a model cannot.

### One observed calibration, and what it suggests

On the one subject node available to back-test in a 2026 run, the pattern was:

- demand centroid alone: **295 km** from the site actually chosen
- pulled 55 per cent toward the **import port** serving that cluster: **93 km**
- pulled toward the **existing trunk origin** instead: **worse at every weight**, up to 925 km

Read as a hypothesis, not a law, because it rests on a single observation: **for an
import-led occupier the node follows the port of entry, not the existing network.** Test it
before relying on it, and expect the opposite for an occupier whose inbound is domestic
production, where the node should follow the plants.

A second, softer pattern from the same occupier's earlier moves: its **first** nodes sat beside
the head office and stayed within 45 km of each other across two relocations. First nodes follow
the founder; later nodes follow the demand and the gateway. Useful when forecasting a business
that has only ever had one node.

## The back-test is not optional

Run the model as at a date just before a node the occupier actually took, and report the error.

- Roll the demand column back as well as the date, or you are testing the location step only.
  Say which you did.
- Report the **cluster** hit or miss and the **km error** separately. Getting the cluster right
  and the sub-market wrong is the usual outcome and is still valuable: it is the difference
  between "they will go to this region" and "they will go to this park".
- **Carry the error as the forecast's error bar.** A forecast that says "this cluster, this zone,
  plus or minus 200 km on the evidence of one back-test" is honest. One that names a town is not.
- **Do not tune parameters until the error vanishes.** With one or two observations that is
  fitting noise, and it will break on the next company. If the occupier has only ever taken one
  node, say that the location rule is uncalibrated.
- Where the occupier has no history, back-test against a **peer's** node choice instead and say
  it is a peer calibration.

## What the brief says

A required section, `## Where the next node probably goes`, after the industry backdrop and
before the persona sections. Its contract:

- **A ranked forecast, two or three clusters**, each with its tier and one line of why. Naming
  only one is overconfident; naming five is useless.
- **The zone, not a town.** A corridor, a triangle between named cities, or a radius, with the
  error bar from the back-test attached.
- **The template**, from how the occupier solved its last cluster: size band, tenure, new build
  against standing stock, landlord type, self-operated against outsourced. Two past nodes are
  enough to describe an occupier's node grammar.
- **The window**, from the trigger and the lead time. "Crosses the peer trigger in about sixteen
  months, against a twelve to eighteen month lead time, so the decision is live now" is a
  sentence with work in it.
- **The falsifier.** What would make this wrong, stated before anyone checks.
- **Three leading indicators**, each with where to look, that would confirm or kill it inside
  ninety days.
- **The label.** This section is an inference. Mark it as one, in the text, every time.

## Leading indicators, in rough order of value

Generic across sectors. The first is the most under-used signal in this whole method.

1. **Company registrations.** A legal entity incorporated in a market with no trading presence
   is a commitment already paid for, and it typically leads trading by around a year. Watch also
   for an existing entity changing its registered address to an industrial one.
2. **Job adverts by location.** A warehouse, transport or site-manager role in a city the
   occupier does not yet operate in is close to proof. Check the occupier's own careers portal
   and the dominant national job boards, not just the international site.
3. **The people.** Supply chain and property staff whose stated location changes, new hires with
   a regional remit, and the absence of a senior role that a decision of this size would need.
4. **Landlord and developer pipelines.** The big-box owners in the candidate zone publish
   leasing activity and availability. A large unit going under offer in the predicted park is
   the confirmation.
5. **Permits and planning registers.** Public, dated, and ahead of any announcement for a build.
6. **Logistics provider announcements.** A third-party contract award is both a confirmation and,
   frequently, the falsifier: see below.
7. **Customs, tax and regulatory registrations** in the candidate market.

## How the forecast dies

State whichever of these applies, in the brief, as the falsifier.

- **They outsource instead of leasing.** The single most common way a node forecast fails: the
  occupier hands the cluster to a logistics provider and appears on no lease. The demand was real,
  the property event never happens. If a close peer has done exactly this, say so.
- **They stretch the existing node instead.** Automation, a mezzanine, a second shift or a
  night-trunk operation buys 30 to 50 per cent more throughput out of the box they have, and it
  is cheaper than a new node. Check whether the existing node was built with the headroom.
- **They flip to franchise or wholesale** in the new markets, which moves the inventory off
  their balance sheet and the node with it.
- **The growth stops**, through a trading shock, an ownership change or a change of chief
  executive. A programme is a forecast too.
- **Someone already signed** and it is not public yet. Which is the reason to run the leading
  indicators before the meeting rather than after.

## Sector notes

The tool is unit-agnostic: `demand_now` is stores, depots, plants, customers or drops. What
changes by sector is the parameters, and they must change.

| Sector | What to change |
|---|---|
| Small-format retail | As written. Demand points are stores; the trigger is stores per node. |
| Grocery and anything chilled | Temperature regimes force far denser networks and the threshold distance collapses. Separate the ambient, chilled and frozen networks: they are three different forecasts. |
| Manufacturing | Inbound follows plants, not ports, so the gateway pull reverses. Model plants and customers as separate demand rows. |
| E-commerce and parcel | The binding constraint is promised delivery time, not cost per km. Replace the distance threshold with a drive-time isochrone from the promise. |
| Third-party logistics | There is no single demand estate. Forecast per contract, and the trigger is contract win or loss, not organic growth. |
| Long-haul geographies | The 700 km road-day proxy is a European road assumption. Re-derive it, and for rail or sea use the real transit time. |

## What not to do

- Do not name a single town and a single building. The method does not support that resolution
  and the room will remember that you did it.
- Do not present the model's ranking as the occupier's decision. They have information you do
  not: a lease event, a tender in progress, a person who prefers a market.
- Do not tune until the back-test error disappears.
- Do not run it at all on an occupier with fewer than about four past market entries and no
  usable peer set. Two data points support a conversation, not a forecast. Say that instead.
- Do not let the forecast displace the question. The best version of this section makes the
  occupier want to correct you, which is how you find out what they are actually doing.
