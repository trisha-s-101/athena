# Instance Setup Guide (for the setup person, no AI needed)

You are getting the IBM Z (LinuxONE) instance ready so the team's app can run on it. You don't need to write any code. Copy each command exactly, press Enter, and compare what you see with the **Expect** line.

**If anything doesn't match what's expected:** stop, take a screenshot or copy the full error text, and send it to Neil. Don't try random fixes.

**Ticking off:** when you finish each part, post "Part N done" in the group chat.

---

## Part 0: Connect to the instance

On your laptop, open a terminal (macOS: Terminal; Windows: PowerShell) and connect the way you normally do, for example:

```bash
ssh -i path/to/your-key.pem linux1@YOUR_INSTANCE_IP
```

**Expect:** a prompt like `linux1@instance:~$`. Every command below is typed into this connected terminal.

---

## Part 1: Check the machine (2 minutes)

```bash
uname -m
```
**Expect:** `s390x`

```bash
cat /etc/os-release | head -3
```
**Expect:** a line containing `Ubuntu 24.04`. If it says something else (for example RHEL or SUSE), **stop and tell Neil**, because the install commands below are for Ubuntu.

```bash
sudo -v
```
**Expect:** either nothing, or a password prompt that accepts your password. If it says you're not allowed to use sudo, **stop and tell Neil.**

---

## Part 2: Install the software (5–10 minutes)

```bash
sudo apt update
```
**Expect:** lines ending in something like `Reading package lists... Done`.

```bash
sudo apt install -y postgresql python3-venv python3-psycopg2 python3-networkx tmux
```
**Expect:** lots of output, ending without the word `E:` (which would mean an error).

```bash
sudo systemctl status postgresql --no-pager
```
**Expect:** the word `active` in green near the top. Press `q` if it doesn't return to the prompt.

---

## Part 3: Set up Python (3–5 minutes)

```bash
python3 -m venv --system-site-packages ~/venv
source ~/venv/bin/activate
```
**Expect:** your prompt now starts with `(venv)`.

```bash
pip install fastapi uvicorn
```
**Expect:** ends with `Successfully installed ...`.

**If it seems stuck compiling for more than 3 minutes:** press `Ctrl+C`, then run:
```bash
sudo apt install -y python3-fastapi python3-uvicorn
```

Check that everything imports:
```bash
python3 -c "import fastapi, uvicorn, psycopg2, networkx; print('allGood')"
```
**Expect:** `allGood`

---

## Part 4: Create the database (2 minutes)

Pick a strong password and write it down somewhere private.

```bash
sudo -u postgres createuser --pwprompt plateletapp
```
**Expect:** it asks for the password twice. Type the password you picked (nothing appears while typing; that's normal).

```bash
sudo -u postgres createdb -O plateletapp plateletexchange
```
**Expect:** no output means success.

Test the login:
```bash
psql "postgresql://plateletapp:YOUR_PASSWORD@localhost:5432/plateletexchange" -c "select 1;"
```
**Expect:** a small table showing `1`.

Save the connection details in a private file on the instance (replace `YOUR_PASSWORD`):
```bash
echo 'export DATABASE_URL="postgresql://plateletapp:YOUR_PASSWORD@localhost:5432/plateletexchange"' > ~/plateletExchange.env
chmod 600 ~/plateletExchange.env
```

**Send Neil the password in a private message only.** Never post it in the group chat or put it in the repo.

---

## Part 5: Get the team's code onto the instance (5 minutes)

```bash
cd ~
git clone https://github.com/OWNER/REPO.git athena
```
Replace `OWNER/REPO` with the repo's address (copy it from the green **Code** button on GitHub).

**If it asks for a username and password** (private repo): the username is your GitHub username, but the password must be a **personal access token**, not your GitHub password. To make one: GitHub → your profile picture → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token → give it access to this repo with "Contents: Read-only" → copy the token and paste it as the password.

**Expect:** `Cloning into 'athena'... done.`

```bash
ls ~/athena
```
**Expect:** you can see `CONTRACT.md` and the other team files.

---

## Part 6: Find out how the dashboard can be reached (10 minutes)

The app will run on **port 8000**. Judges or teammates need to open it in a browser.

1. In the instance's web console (where the instance was created), look for **firewall**, **security group**, or **network rules**. Check whether you can allow incoming traffic on **port 8000 (TCP)**. If you can, add that rule.
2. Then check what's listening right now:
   ```bash
   sudo ss -tlnp
   ```
   Send Neil a screenshot of the output.

**If port 8000 can't be opened**, that's fine; there's a backup plan. Anyone with SSH access can run this **on their own laptop**:
```bash
ssh -i path/to/your-key.pem -L 8000:localhost:8000 linux1@YOUR_INSTANCE_IP
```
and then open `http://localhost:8000` in their browser while that terminal stays open.

**Tell Neil which of the two options works.**

---

## Part 7: Report back

Post this in the group chat (password to Neil privately):

```
Instance setup done.
uname: s390x
OS: Ubuntu 24.04 (or what it said)
Postgres: active
Python check: allGood
Repo cloned to: ~/athena
Port 8000 open: yes / no (use SSH tunnel)
Problems: none / (describe)
```

---

## Part 8: Deploying new versions (repeat whenever Neil asks)

The app runs inside **tmux**, so it keeps running after you disconnect:
- Start a session: `tmux new -s app`
- Leave it running: press `Ctrl+B`, then `D`
- Come back to it: `tmux attach -t app`
- Stop the app: inside the session, press `Ctrl+C`
- Check you're inside tmux: there's a **green bar along the bottom** of the screen. No green bar means you're not in tmux, and the app will stop when you disconnect.

**Mac keyboards:** `Ctrl` means the **control (⌃)** key, not Command. `Ctrl+B`, then `D` means: hold control and press `b`, **let go of both**, then press a **lowercase** `d` on its own. Shift+D opens a menu instead; if that happens, press `q` and try again. `Ctrl+C` is control + `c` (Command+C only copies text).

Port 8000 isn't open, so the app only listens inside the instance, and everyone reaches it through the SSH tunnel from Part 6.

### 8A: First start (do this once)

Connect to the instance (Part 0), then start a tmux session:

```bash
tmux new -s app
```
**Expect:** the screen clears and a green bar appears at the bottom. Everything below is typed inside this session.

Load the Python environment and the database password. These must be run **inside** tmux, every time you start a new session:

```bash
source ~/venv/bin/activate
source ~/plateletExchange.env
cd ~/athena
```
**Expect:** your prompt starts with `(venv)`.

Get the latest code:

```bash
git pull
```
**Expect:** a list of changed files, or `Already up to date.` If it asks for a username and password, use your GitHub username and the token from Part 5.

Create the database tables and load the hospitals:

```bash
python -m db.seed
```
**Expect:** `Seeded: 10 hospitals, 90 travel times` (the numbers may differ). If it says `Seed failed: Missing .../shared/hospitals.json`, the hospital data isn't in the repo yet. **Stop and tell Neil.**

Check that the code works on this machine:

```bash
python -m unittest discover api/tests
```
**Expect:** the last line starts with `OK`, for example `OK (skipped=11)`. The number can change between versions. Skipped tests are normal: they need a test database that the instance doesn't have. If it says `FAILED`, stop and send Neil the output.

Start the app. `ulimit -n 4096` lets it hold enough connections open for the benchmarks in Part 10; it prints nothing:

```bash
ulimit -n 4096
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```
**Wait** until you see a line containing `Uvicorn running on http://127.0.0.1:8000`. It keeps running and doesn't return to the prompt. That's correct.

Only then, leave it running: press `Ctrl+B`, let go, then press lowercase `d` (see the Mac note above).
**Expect:** the green bar disappears and you see `[detached (from session app)]`. If you don't see that message, you weren't inside tmux: **stop and tell Neil.**

Check the app answers:

```bash
curl -sS localhost:8000/api/health
```
**Expect:** `{"status":"ok","arch":"s390x","dbOk":true}`. If `dbOk` is `false`, or `curl` prints an error or nothing at all, see Troubleshooting.

Check the app will keep running after you disconnect:

```bash
tmux ls
```
**Expect:** a line starting with `app:`.

### 8B: Open the dashboard (on your laptop)

Open a **new terminal on your laptop** (not connected to the instance) and run the tunnel from Part 6:

```bash
ssh -i path/to/your-key.pem -L 8000:localhost:8000 linux1@YOUR_INSTANCE_IP
```
Keep that terminal open. Then open **http://localhost:8000** in your browser and untick **Use mock data** at the top right.
**Expect:** the status next to it changes to `● API connected`. Anyone else with the SSH key can do the same on their own laptop.

### 8C: Deploying a new version (whenever Neil asks)

Connect to the instance, then go back into the running session:

```bash
tmux attach -t app
```
**Expect:** the green bar and the running app. If it says `no sessions` or `no server running`, the app isn't running anymore: do **8A** from the start instead.

Press `Ctrl+C` to stop the app. **Expect:** your prompt comes back.

If `results/benchmark.json` exists from a benchmark run, move it aside first (the repo now has its own copy, and `git pull` refuses to overwrite yours):

```bash
mv -f results/benchmark.json ~/benchmark-backup.json 2>/dev/null; true
```

Get the latest code on its own first, because it may ask for your token:

```bash
git pull
```

Then run these:

```bash
python -m db.seed
python -m unittest discover api/tests
ulimit -n 4096
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```
**Expect:** the same results as in 8A. `python -m db.seed` is safe to run every time: it only adds what's missing and never deletes live data.

**Wait** for `Uvicorn running on http://127.0.0.1:8000`, then press `Ctrl+B`, let go, and press lowercase `d`. Run the `curl -sS` and `tmux ls` checks from 8A. Post "Deployed" in the group chat.

### 8D: Wiping the database (only when Neil asks)

This deletes every unit, reservation and event, for example before a rehearsal. Stop the app first (8C), then:

```bash
python -m db.seed --reset
```
**Expect:** `Reset and seeded: ...`. Start the app again as in 8C.

---

## Part 9: Running live mode (the sim feeding the dashboard)

Live mode replays a simulated scenario into the app: units are delivered, used and expire, and the dashboard updates every 5 seconds. It runs in its **own** tmux session called `sim`, next to the app's session.

The app must already be running (Part 8). Check:

```bash
curl -sS localhost:8000/api/health
```
**Expect:** `{"status":"ok","arch":"s390x","dbOk":true}`

### 9A: Start a live run

Start a second tmux session:

```bash
tmux new -s sim
```
**Expect:** the green bar at the bottom.

```bash
source ~/venv/bin/activate
source ~/plateletExchange.env
cd ~/athena
```

**Wipe the database first, every time.** A new run replays the same units from the start, and the app rejects units it has already seen. This is safe while the app is running:

```bash
python -m db.seed --reset
```
**Expect:** `Reset and seeded: 10 hospitals, 90 travel times`

Start the stream:

```bash
python -m sim.live --api http://localhost:8000 --speed 1440
```
**Expect:** `[sim.live] API healthy: ...`, then `[sim.live] Streaming 90 days ...`, then a new line about every 15 seconds starting `[sim.live] 2026-01-05T...`. `--speed 1440` runs one sim day per real minute, so a full 90-day run takes about 90 minutes. Neil may ask for a different speed for the demo.

Leave it running: press `Ctrl+B`, let go, then press lowercase `d`.
**Expect:** `[detached (from session sim)]`.

### 9B: Check it's working

```bash
curl -sS localhost:8000/api/metrics
```
**Expect:** `simTime` moving forward each time you run it, and `unitsAvailable` above 0.

On the dashboard (Part 8B), hospitals fill with stock. **Recommended transfers** appear after about one sim day (about a minute at `--speed 1440`), once there's demand history to forecast from.

### 9C: Stop a live run

```bash
tmux attach -t sim
```
Press `Ctrl+C`. **Expect:** your prompt comes back. The data stays in the database until the next wipe. To start again, go back to 9A's wipe step. When a run finishes on its own, it prints `[sim.live] Done. Events sent:` and a count of each event type.

---

## Part 10: Running the benchmarks (only when Neil asks)

These produce the mainframe numbers for the pitch: 1,000 people trying to reserve the same unit at the same moment (exactly one must succeed), and how fast each part of the app answers. They take about two minutes and add test data, so the database is wiped before and after.

The app must be running (Part 8), and live mode must be **stopped** (9C).

### 10A: Run them

In any window connected to the instance (tmux isn't needed, as long as you stay connected until they finish):

```bash
source ~/venv/bin/activate
source ~/plateletExchange.env
cd ~/athena
ulimit -n 4096
python -m db.seed --reset
```
**Expect:** `Reset and seeded: 10 hospitals, 90 travel times`. (`ulimit -n 4096` lets this window hold 1,000 connections open at once. It prints nothing.)

The reservation race:

```bash
python -m bench.reserveRace
```
**Expect:** `arch s390x: 1000 concurrent reservations -> 1 accepted, 999 conflicts, 0 other`, then a line starting `[bench.reserveRace] PASSED`. If it says `FAILED`, **stop and send Neil the output.**

The speed test:

```bash
python -m bench.latency
```
**Expect:** one line per endpoint, each ending in `errors 0`, then `Wrote .../results/benchmark.json`.

### 10B: Send Neil the results

```bash
cat results/benchmark.json
```
Copy everything it prints and send it to Neil. It contains only timings, no passwords. The dashboard's benchmark panel also reads it straight from the app.

Then wipe the test data:

```bash
python -m db.seed --reset
```

---

## Troubleshooting

| What you see | What to do |
|---|---|
| `Permission denied (publickey)` when connecting | Wrong key file or username. Check the instance console for the right username. |
| `E: Unable to locate package ...` | Run `sudo apt update` again, then retry. If it still fails, send Neil the exact package name. |
| `Could not get lock /var/lib/dpkg/lock` | Another install is running. Wait 2 minutes and retry. |
| `(venv)` disappeared from your prompt | You reconnected. Run `source ~/venv/bin/activate` again. |
| `psql: ... password authentication failed` | The password was typed wrong. Ask Neil to help reset it. |
| `DATABASE_URL is not set` from `db.seed`, or `"dbOk":false` | The password file wasn't loaded in this tmux session. `tmux attach -t app`, press `Ctrl+C`, run `source ~/plateletExchange.env`, then start the app again. |
| `No module named 'api'` or `No module named 'db'` | You're in the wrong folder. Run `cd ~/athena` and try again. |
| `No module named 'fastapi'` (or `uvicorn`, `psycopg2`) | The Python environment isn't loaded. Run `source ~/venv/bin/activate` and try again. |
| `address already in use` when starting the app | The app is already running in another session. Run `tmux attach -t app` instead of starting a new one. |
| `duplicate session: app` | A session already exists. Use `tmux attach -t app` instead of `tmux new -s app`. |
| `curl` prints nothing, `Connection refused`, or `Failed to connect` | The app isn't running. Run `tmux attach -t app` and look at the screen: if it's a plain prompt, start the app again (the `python -m uvicorn ...` line) and wait for `Uvicorn running`. If there's an error, send Neil the text. |
| `no sessions` or `no server running` from `tmux attach` | The tmux session is gone, so the app stopped. Do 8A from the start. |
| `Ctrl+B`, `D` does nothing, or the app stops when you disconnect | You weren't inside tmux (no green bar at the bottom). Do 8A from the start, beginning with `tmux new -s app`. |
| A list pops up after `Ctrl+B` | You pressed Shift+D. Press `q`, then `Ctrl+B` and lowercase `d`. |
| `[sim.live] POST failed (HTTP Error 409: Conflict)` and `event(s) failed to post` | The database wasn't wiped before this run. Stop the run (9C), then do 9A again from the wipe step. |
| `[sim.live] Cannot reach http://localhost:8000/api/health` | The app isn't running. Start it (Part 8), then start live mode again. |
| `duplicate session: sim` | A live run session already exists. Use `tmux attach -t sim` to see it. |
| `bench.reserveRace` shows `other` above 0, or the app window says `Too many open files` | The app ran out of connections. `tmux attach -t app`, press `Ctrl+C`, run `ulimit -n 4096`, start the app again (8C), then rerun 10A. |
| `API health check failed` or `The API reports dbOk false` from a benchmark | The app isn't running or can't reach the database. Fix that first (Part 8), then rerun 10A. |
| `git pull` says `untracked working tree files would be overwritten` and names `results/benchmark.json` | Run `mv results/benchmark.json ~/benchmark-backup.json`, then `git pull` again. |
| Laptop tunnel says `bind: Address already in use` | Something on your laptop already uses port 8000. Use `-L 8001:localhost:8000` and open http://localhost:8001 instead. |
| Browser says it can't connect to localhost:8000 | The tunnel terminal was closed or disconnected. Run the `ssh -L ...` command again. |
| Anything else | Screenshot it and send it to Neil. |
