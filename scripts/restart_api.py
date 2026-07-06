#!/usr/bin/env python3
"""Restart Karma API server after git pull."""
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('156.236.116.140', port=54542, username='root', password='KXuqn7r4GQUv')

# Check logs first
_, stdout, _ = ssh.exec_command('tail -30 /tmp/karma-api.log')
print("=== API Log ===")
print(stdout.read().decode()[:2000])

# Kill any existing uvicorn
_, stdout, _ = ssh.exec_command('pkill -f "uvicorn api.app" 2>&1; sleep 2; echo "killed"')
print(stdout.read().decode())

# Start fresh
_, stdout, _ = ssh.exec_command('cd /root/karma && nohup python3 -m uvicorn api.app:app --host 0.0.0.0 --port 8000 --workers 1 > /tmp/karma-api.log 2>&1 & echo "started:$!"')
time.sleep(5)
print(stdout.read().decode())

# Check it's running
_, stdout, _ = ssh.exec_command('ps aux | grep "uvicorn" | grep -v grep')
print("=== Running ===")
print(stdout.read().decode())

# Check health
_, stdout, _ = ssh.exec_command('curl -s http://127.0.0.1:8000/health 2>&1')
print("=== Health ===")
print(stdout.read().decode()[:500])

ssh.close()
