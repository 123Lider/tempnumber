#!/usr/bin/env python3
"""
TempNum Android SMS Forwarder
Run this on Termux on your Android device to forward SMS to your server
"""

import json
import time
import argparse
import subprocess
import re
import urllib.request
import urllib.error

# ==================== CONFIGURATION ====================

SERVER_URL = "http://YOUR_SERVER_IP:5000"  # Change this to your server URL
HEARTBEAT_INTERVAL = 30  # seconds
SMS_CHECK_INTERVAL = 5  # seconds

# ==================== SMS PARSING ====================

def get_sms_from_device():
    """Get SMS from Android device using content://sms/inbox"""
    try:
        # Use content provider to read SMS
        result = subprocess.run(
            ['content', 'query', '--uri', 'content://sms/inbox',
             '--projection', 'address,body,date', '--sort', 'date DESC',
             '--limit', '20'],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode != 0:
            print(f"[!] Error reading SMS: {result.stderr}")
            return []
        
        messages = []
        current_msg = {}
        
        for line in result.stdout.split('\n'):
            line = line.strip()
            
            if line.startswith('address='):
                current_msg['sender'] = line.replace('address=', '').strip()
            elif line.startswith('body='):
                current_msg['body'] = line.replace('body=', '').strip()
                if 'sender' in current_msg and 'body' in current_msg:
                    messages.append(current_msg)
                    current_msg = {}
        
        return messages
        
    except Exception as e:
        print(f"[!] Error: {e}")
        return []

def get_sms_android_sdk():
    """Alternative: Use Android SDK's sms database"""
    # This requires root or specific permissions
    # Using the 'sm' command-line tool if available
    try:
        result = subprocess.run(
            ['sm', 'list', 'sms'], 
            capture_output=True, text=True, timeout=5
        )
        
        if result.returncode == 0:
            # Parse SMS from output
            sms_list = []
            lines = result.stdout.strip().split('\n')
            for line in lines:
                parts = line.split('|')
                if len(parts) >= 3:
                    sms_list.append({
                        'sender': parts[0].strip(),
                        'body': parts[1].strip(),
                        'timestamp': parts[2].strip()
                    })
            return sms_list
    except:
        pass
    
    return []

# ==================== NETWORK FUNCTIONS ====================

def send_sms_to_server(messages, token):
    """Send SMS messages to the server"""
    if not messages:
        return
    
    url = f"{SERVER_URL}/api/sms/receive"
    
    for msg in messages:
        data = json.dumps({
            'sender': msg['sender'],
            'body': msg['body'],
            'device_id': 'android_termux_1'
        }).encode('utf-8')
        
        req = urllib.request.Request(
            url, 
            data=data,
            headers={
                'Content-Type': 'application/json',
                'X-API-Token': token
            },
            method='POST'
        )
        
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode())
                if result.get('success'):
                    print(f"[+] Sent: {msg['sender']} -> {msg['body'][:50]}...")
                else:
                    print(f"[!] Failed to send: {result}")
        except urllib.error.HTTPError as e:
            print(f"[!] HTTP Error {e.code}: {e.read().decode()}")
        except Exception as e:
            print(f"[!] Network Error: {e}")

def send_heartbeat(token, device_id="android_termux_1"):
    """Send heartbeat to server"""
    url = f"{SERVER_URL}/api/device/heartbeat"
    
    data = json.dumps({
        'device_id': device_id,
        'device_name': 'Android Termux SMS Forwarder'
    }).encode('utf-8')
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'X-API-Token': token
        },
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return True
    except:
        return False

# ==================== MAIN LOOP ====================

def main():
    parser = argparse.ArgumentParser(description='TempNum Android SMS Forwarder')
    parser.add_argument('--token', '-t', required=True, help='Your API token from TempNum dashboard')
    parser.add_argument('--server', '-s', default=SERVER_URL, help='Server URL')
    parser.add_argument('--device-id', '-d', default='android_termux_1', help='Device identifier')
    
    args = parser.parse_args()
    
    global SERVER_URL
    SERVER_URL = args.server
    
    token = args.token
    device_id = args.device_id
    
    print("=" * 50)
    print("📱 TempNum Android SMS Forwarder")
    print("=" * 50)
    print(f"Server: {SERVER_URL}")
    print(f"Device: {device_id}")
    print(f"Token: {token[:16]}...")
    print("=" * 50)
    print("[*] Starting SMS forwarding...")
    print("[*] Press Ctrl+C to stop")
    print("=" * 50)
    
    last_heartbeat = 0
    processed_ids = set()
    
    try:
        while True:
            current_time = time.time()
            
            # Send heartbeat every HEARTBEAT_INTERVAL seconds
            if current_time - last_heartbeat > HEARTBEAT_INTERVAL:
                if send_heartbeat(token, device_id):
                    print("[✓] Heartbeat sent")
                else:
                    print("[!] Heartbeat failed")
                last_heartbeat = current_time
            
            # Get new SMS
            try:
                messages = get_sms_from_device()
                
                if messages:
                    # Filter out already processed messages (using timestamp as simple ID)
                    new_messages = []
                    for msg in messages:
                        msg_id = f"{msg['sender']}:{msg['body'][:50]}"
                        if msg_id not in processed_ids:
                            new_messages.append(msg)
                            processed_ids.add(msg_id)
                    
                    if new_messages:
                        print(f"[*] Found {len(new_messages)} new message(s)")
                        send_sms_to_server(new_messages, token)
                    
                    # Keep processed_ids from growing too large
                    if len(processed_ids) > 1000:
                        processed_ids = set(list(processed_ids)[-500:])
                
            except Exception as e:
                print(f"[!] SMS check error: {e}")
            
            time.sleep(SMS_CHECK_INTERVAL)
    
    except KeyboardInterrupt:
        print("\n[*] Stopping SMS forwarder...")
        print("[✓] Goodbye!")

if __name__ == '__main__':
    main()
