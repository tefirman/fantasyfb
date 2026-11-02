# Web app

The [fantasyfb web app](https://fantasy.taylorfirman.com/) runs the package's season simulation for a Sleeper or Yahoo league with nothing to install, and shows the same interactive HTML report that `fantasyfb --format html` writes. It is the quickest way to try fantasyfb, and the right choice if you don't want to set up Python.

## Using it

1. **Pick a platform.** For Sleeper, paste your league URL or ID. The Sleeper API is public, so no sign-in is needed. For Yahoo, sign in with Yahoo and approve read-only access.
2. **Pick your team** from the league's teams.
3. **Choose the number of simulations**, any whole number from 100 to 10,000 (default 1,000). More is slower in proportion.
4. **Run.** The progress page updates on its own and turns into the report when the run finishes. The report URL is a random link, so a Sleeper run can be shared. A Yahoo run belongs to the session that started it.

The report has standings and playoff odds, your weekly outlook, free agents, and a Moves tab with adds and drops, plus a rooting guide that shows which games help your team most. You can download the report as an HTML file, and add the app to an iPhone or Android home screen for a full-screen launch.

## Scott Fish Bowl leagues

Sleeper leagues named like `#SFB16` are detected by name. They use the SFB's 11-week regular season, count the median-game win, and show the chance of reaching 13 or more wins in place of a made-up in-league bracket. That number is a lower bound on qualifying, because the rest of the SFB field is filled by points across all leagues. For odds that account for the whole field, see [`sfb-field`](cli/sfb-field.md).

## What it doesn't do

- **Runs are temporary.** Finished runs are kept for a few hours. Opening an older link shows a page saying the run has expired, with a button to start a new one. Download the report if you want to keep it.
- **One run at a time per visitor**, and runs queue when the app is busy. Each run has a time limit.
- **Pickups and trades aren't offered**, only adds, drops, and the rooting guide. Use the package for those.
- **Best ball leagues** are run as redraft, because Sleeper's best ball setting isn't read yet.
- **Sleeper has no roster percentages**, so free agents are ranked by Sleeper's own popularity rank and limited to players with an NFL team, and adds are tested for only the top few per position.
- **It never changes your league.** The app only reads from Sleeper and Yahoo. Nothing in fantasyfb writes to a platform.

## Privacy

Your Yahoo password never reaches the app. Yahoo's access tokens are kept in server memory only, are never written to disk or logs, and are dropped on sign out, after two idle hours, and on restart. See [`app/README.md`](https://github.com/tefirman/fantasyfb/blob/main/app/README.md) for the full security model, how to run the app yourself, and how it is deployed.

## Web app or package?

| You want to                                              | Use                          |
| -------------------------------------------------------- | ---------------------------- |
| Try fantasyfb, or check a Sleeper league from your phone | The web app                  |
| Pickups, trades, or Excel output                         | The package                  |
| Draft tools (snake, salary cap, tiers, mocks)            | The package                  |
| A custom scoring setup or scripting against `League`     | The package                  |
