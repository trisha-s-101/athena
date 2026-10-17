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
git clone https://github.com/OWNER/REPO.git plateletExchange
```
Replace `OWNER/REPO` with the repo's address (copy it from the green **Code** button on GitHub).

**If it asks for a username and password** (private repo): the username is your GitHub username, but the password must be a **personal access token**, not your GitHub password. To make one: GitHub → your profile picture → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token → give it access to this repo with "Contents: Read-only" → copy the token and paste it as the password.

**Expect:** `Cloning into 'plateletExchange'... done.`

```bash
ls ~/plateletExchange
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
Repo cloned to: ~/plateletExchange
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
cd ~/plateletExchange
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
**Expect:** the last line says `OK (skipped=9)`. Skipped tests are normal: they need a test database that the instance doesn't have.

Start the app:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```
**Expect:** a line containing `Uvicorn running on http://127.0.0.1:8000`. It keeps running and doesn't return to the prompt. That's correct.

Leave it running: press `Ctrl+B`, let go, then press `D`.
**Expect:** you're back at your normal prompt, with `[detached (from session app)]`.

Check the app answers:

```bash
curl -s localhost:8000/api/health
```
**Expect:** `{"status":"ok","arch":"s390x","dbOk":true}`. If `dbOk` is `false`, see Troubleshooting.

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
Press `Ctrl+C` to stop the app. **Expect:** your prompt comes back.

```bash
git pull
python -m db.seed
python -m unittest discover api/tests
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```
**Expect:** the same results as in 8A. `python -m db.seed` is safe to run every time: it only adds what's missing and never deletes live data.

Press `Ctrl+B`, then `D` to leave it running, and run the `curl` check from 8A. Post "Deployed" in the group chat.

### 8D: Wiping the database (only when Neil asks)

This deletes every unit, reservation and event, for example before a rehearsal. Stop the app first (8C), then:

```bash
python -m db.seed --reset
```
**Expect:** `Reset and seeded: ...`. Start the app again as in 8C.

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
| `No module named 'api'` or `No module named 'db'` | You're in the wrong folder. Run `cd ~/plateletExchange` and try again. |
| `No module named 'fastapi'` (or `uvicorn`, `psycopg2`) | The Python environment isn't loaded. Run `source ~/venv/bin/activate` and try again. |
| `address already in use` when starting the app | The app is already running in another session. Run `tmux attach -t app` instead of starting a new one. |
| `duplicate session: app` | A session already exists. Use `tmux attach -t app` instead of `tmux new -s app`. |
| Laptop tunnel says `bind: Address already in use` | Something on your laptop already uses port 8000. Use `-L 8001:localhost:8000` and open http://localhost:8001 instead. |
| Browser says it can't connect to localhost:8000 | The tunnel terminal was closed or disconnected. Run the `ssh -L ...` command again. |
| Anything else | Screenshot it and send it to Neil. |
