import os
import time
import requests
from app import create_app, db
from app.models.user import User
from app.models.sms import SMSNumber, SMSCDR
from app.models.activity import News

# In-memory dictionary to track requested numbers
# Format: { "number": { "chat_id": 123456, "requested_at": timestamp } }
requested_numbers = {}

def get_settings():
    settings = {}
    items = News.query.all()
    for item in items:
        if item.title.startswith('test123_'):
            settings[item.title] = item.content
    return settings

def set_number_request(number, chat_id):
    import json
    title = f'test123_req_{number}'
    item = News.query.filter_by(title=title).first()
    expires_at = time.time() + 600 # 10 minutes
    content = json.dumps({'chat_id': chat_id, 'expires_at': expires_at})
    if item:
        item.content = content
    else:
        item = News(title=title, content=content, is_active=1)
        db.session.add(item)
    db.session.commit()

def get_requested_numbers():
    import json
    now = time.time()
    items = News.query.filter(News.title.like('test123_req_%')).all()
    requested = {}
    for item in items:
        try:
            data = json.loads(item.content)
            if data['expires_at'] > now:
                number = item.title.replace('test123_req_', '')
                requested[number] = data['chat_id']
        except:
            pass
    return requested

def send_message(token, chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except Exception as e:
        print(f"Failed to send message: {e}")

def handle_admin_commands(text, chat_id, token, test123_user):
    parts = text.split()
    cmd = parts[0].lower()
    
    if cmd == '/start':
        send_message(token, chat_id, "Welcome Admin! Use /add <number>, /remove <number>, /numbers to manage the pool.")
        
    elif cmd == '/add' and len(parts) > 1:
        number = parts[1].replace('+', '').strip()
        existing = SMSNumber.query.filter_by(number=number).first()
        if existing:
            if existing.agent_id == test123_user.id or existing.client_id == test123_user.id:
                send_message(token, chat_id, f"Number {number} is already in the pool.")
            else:
                send_message(token, chat_id, f"Number {number} is owned by another user.")
        else:
            new_num = SMSNumber(number=number, agent_id=test123_user.id, status='active')
            db.session.add(new_num)
            db.session.commit()
            send_message(token, chat_id, f"Number {number} added to the pool successfully.")
            
    elif cmd == '/remove' and len(parts) > 1:
        number = parts[1].replace('+', '').strip()
        num = SMSNumber.query.filter_by(number=number).first()
        if num and (num.agent_id == test123_user.id or num.client_id == test123_user.id):
            db.session.delete(num)
            db.session.commit()
            send_message(token, chat_id, f"Number {number} removed from the pool.")
        else:
            send_message(token, chat_id, f"Number {number} not found in test123 pool.")
            
    elif cmd == '/numbers':
        nums = SMSNumber.query.filter((SMSNumber.agent_id == test123_user.id) | (SMSNumber.client_id == test123_user.id)).all()
        if not nums:
            send_message(token, chat_id, "No numbers in the pool.")
        else:
            num_list = "\n".join([f"- {n.number}" for n in nums])
            send_message(token, chat_id, f"Total numbers ({len(nums)}):\n{num_list}")
    else:
        send_message(token, chat_id, "Unknown admin command.")

def handle_user_commands(text, chat_id, token, test123_user):
    parts = text.split()
    cmd = parts[0].lower()
    
    if cmd == '/start':
        send_message(token, chat_id, "Welcome! Use /request to get a number.")
        
    elif cmd == '/request':
        nums = SMSNumber.query.filter((SMSNumber.agent_id == test123_user.id) | (SMSNumber.client_id == test123_user.id)).all()
        if not nums:
            send_message(token, chat_id, "No numbers available at the moment.")
            return
            
        requested = get_requested_numbers()
                
        # Find a number that is not currently requested
        available_num = None
        for n in nums:
            if n.number not in requested:
                available_num = n.number
                break
                
        if available_num:
            set_number_request(available_num, chat_id)
            send_message(token, chat_id, f"You have requested number:\n+{available_num}\n\nAny OTP received in the next 10 minutes will be sent to you.")
        else:
            # If all are requested, just give a random one and overwrite
            import random
            available_num = random.choice(nums).number
            set_number_request(available_num, chat_id)
            send_message(token, chat_id, f"You have requested number:\n+{available_num}\n\nAny OTP received in the next 10 minutes will be sent to you.")
            
    else:
        send_message(token, chat_id, "Use /request to get a number.")

def process_pending_otps(app, token, channel_id):
    """
    Checks if there are any new OTPs for requested numbers.
    Normally the webhook handles this, but since we are polling here,
    we could also just let the webhook trigger this if we want.
    Wait, the webhook is a separate process! The webhook in api.py does not have access to `requested_numbers` in this script.
    """
    pass

def main():
    app = create_app()
    with app.app_context():
        print("Starting Telegram Bot for test123...")
        last_update_id = 0
        
        while True:
            try:
                settings = get_settings()
                if settings.get('test123_enabled') != 'true':
                    time.sleep(10)
                    continue
                    
                bot_token = settings.get('test123_bot_token')
                if not bot_token:
                    time.sleep(10)
                    continue
                    
                test123_user = User.query.filter_by(username='test123').first()
                if not test123_user:
                    print("User test123 not found!")
                    time.sleep(10)
                    continue
                    
                url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
                resp = requests.get(url, params={"offset": last_update_id + 1, "timeout": 30}, timeout=35)
                data = resp.json()
                
                if data.get("ok"):
                    for update in data.get("result", []):
                        last_update_id = update["update_id"]
                        message = update.get("message")
                        if not message or "text" not in message:
                            continue
                            
                        chat_id = message["chat"]["id"]
                        text = message["text"].strip()
                        admin_chat_id = settings.get("test123_admin_chat_id", "")
                        
                        is_admin = str(chat_id) == str(admin_chat_id)
                        
                        if is_admin and (text.startswith('/add') or text.startswith('/remove') or text.startswith('/numbers') or (text.startswith('/start') and len(text.split()) == 1)):
                            handle_admin_commands(text, chat_id, bot_token, test123_user)
                        else:
                            handle_user_commands(text, chat_id, bot_token, test123_user)
                            
            except Exception as e:
                print(f"Error polling: {e}")
                time.sleep(5)
                
if __name__ == '__main__':
    main()
