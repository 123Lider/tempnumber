import os
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse
import random
import string

from config import Config

app = Flask(__name__)
app.config.from_object(Config)
app.config['SQLALCHEMY_DATABASE_URI'] = Config.DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==================== DATABASE MODELS ====================

class PhoneNumber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    messages = db.relationship('Message', backref='phone_number', lazy=True, cascade='all, delete-orphan')
    
    def is_expired(self):
        return datetime.utcnow() > self.expires_at
    
    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'message_count': len(self.messages)
        }

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone_number_id = db.Column(db.Integer, db.ForeignKey('phone_number.id'), nullable=False)
    from_number = db.Column(db.String(20), nullable=False)
    to_number = db.Column(db.String(20), nullable=False)
    body = db.Column(db.Text, nullable=True)
    media_urls = db.Column(db.Text, nullable=True)  # Comma-separated URLs
    message_type = db.Column(db.String(10), default='sms')  # 'sms' or 'call'
    call_recording_url = db.Column(db.String(500), nullable=True)
    call_duration = db.Column(db.Integer, nullable=True)  # seconds
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'from_number': self.from_number,
            'to_number': self.to_number,
            'body': self.body,
            'media_urls': self.media_urls.split(',') if self.media_urls else [],
            'message_type': self.message_type,
            'call_recording_url': self.call_recording_url,
            'call_duration': self.call_duration,
            'received_at': self.received_at.isoformat()
        }

# ==================== NUMBERS MANAGEMENT ====================

def generate_temp_number():
    """Generate a random temporary number (simulated)"""
    area_codes = ['212', '310', '415', '617', '312', '404', '713', '602', '206', '305']
    area = random.choice(area_codes)
    prefix = ''.join(random.choices(string.digits, k=3))
    line = ''.join(random.choices(string.digits, k=4))
    return f"+1{area}{prefix}{line}"

def assign_twilio_number():
    """Search and buy a Twilio number (production)"""
    client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
    
    # Search for available numbers
    available = client.available_phone_numbers("US").local.list(limit=5)
    
    if not available:
        return None
    
    # Buy the first available number
    purchased = client.incoming_phone_numbers.create(
        phone_number=available[0].phone_number,
        sms_url=url_for('sms_webhook', _external=True),
        voice_url=url_for('voice_webhook', _external=True)
    )
    
    return purchased.phone_number

# ==================== ROUTES ====================

@app.route('/')
def index():
    """Homepage - list active numbers"""
    active_numbers = PhoneNumber.query.filter_by(is_active=True)\
        .filter(PhoneNumber.expires_at > datetime.utcnow())\
        .order_by(desc(PhoneNumber.created_at)).all()
    
    expired_numbers = PhoneNumber.query.filter(
        (PhoneNumber.is_active == False) | (PhoneNumber.expires_at <= datetime.utcnow())
    ).order_by(desc(PhoneNumber.created_at)).limit(10).all()
    
    return render_template('index.html', 
                         active_numbers=active_numbers,
                         expired_numbers=expired_numbers)

@app.route('/numbers/new', methods=['POST'])
def create_number():
    """Create a new temporary number"""
    duration = request.form.get('duration', 60)  # minutes
    
    # In production, this would buy a real Twilio number
    # number_str = assign_twilio_number()
    
    # For development, generate a simulated number
    number_str = generate_temp_number()
    
    new_number = PhoneNumber(
        number=number_str,
        expires_at=datetime.utcnow() + timedelta(minutes=int(duration))
    )
    
    db.session.add(new_number)
    db.session.commit()
    
    flash(f'New number created: {number_str} (expires in {duration} minutes)', 'success')
    return redirect(url_for('inbox', number_id=new_number.id))

@app.route('/numbers/<int:number_id>/delete', methods=['POST'])
def delete_number(number_id):
    """Delete a temporary number"""
    number = PhoneNumber.query.get_or_404(number_id)
    number.is_active = False
    db.session.commit()
    
    flash(f'Number {number.number} has been deactivated', 'info')
    return redirect(url_for('index'))

@app.route('/inbox/<int:number_id>')
def inbox(number_id):
    """View messages for a specific number"""
    number = PhoneNumber.query.get_or_404(number_id)
    messages = Message.query.filter_by(phone_number_id=number_id)\
        .order_by(desc(Message.received_at)).all()
    
    return render_template('inbox.html', number=number, messages=messages)

@app.route('/message/<int:message_id>')
def message_detail(message_id):
    """View a single message detail"""
    message = Message.query.get_or_404(message_id)
    return render_template('message_detail.html', message=message)

@app.route('/api/numbers')
def api_numbers():
    """API endpoint to list numbers"""
    numbers = PhoneNumber.query.filter_by(is_active=True)\
        .filter(PhoneNumber.expires_at > datetime.utcnow()).all()
    return jsonify([n.to_dict() for n in numbers])

@app.route('/api/numbers/<int:number_id>/messages')
def api_messages(number_id):
    """API endpoint to get messages for a number"""
    messages = Message.query.filter_by(phone_number_id=number_id)\
        .order_by(desc(Message.received_at)).all()
    return jsonify([m.to_dict() for m in messages])

# ==================== TWILIO WEBHOOKS ====================

@app.route('/webhook/sms', methods=['POST'])
def sms_webhook():
    """Handle incoming SMS from Twilio"""
    from_number = request.form.get('From')
    to_number = request.form.get('To')
    body = request.form.get('Body')
    num_media = int(request.form.get('NumMedia', 0))
    
    # Find the phone number in our database
    phone = PhoneNumber.query.filter_by(number=to_number, is_active=True).first()
    
    if not phone:
        # Number not found or inactive
        resp = MessagingResponse()
        resp.message("This number is not active or has expired.")
        return str(resp)
    
    if phone.is_expired():
        phone.is_active = False
        db.session.commit()
        resp = MessagingResponse()
        resp.message("This number has expired.")
        return str(resp)
    
    # Collect media URLs
    media_urls = []
    for i in range(num_media):
        media_url = request.form.get(f'MediaUrl{i}')
        if media_url:
            media_urls.append(media_url)
    
    # Save the message
    message = Message(
        phone_number_id=phone.id,
        from_number=from_number,
        to_number=to_number,
        body=body,
        media_urls=','.join(media_urls) if media_urls else None,
        message_type='sms'
    )
    
    db.session.add(message)
    db.session.commit()
    
    # Return empty TwiML response
    return str(MessagingResponse())

@app.route('/webhook/voice', methods=['POST'])
def voice_webhook():
    """Handle incoming calls from Twilio"""
    from_number = request.form.get('From')
    to_number = request.form.get('To')
    call_sid = request.form.get('CallSid')
    
    # Find the phone number
    phone = PhoneNumber.query.filter_by(number=to_number, is_active=True).first()
    
    response = VoiceResponse()
    
    if not phone or phone.is_expired():
        response.say("This number is not available.", voice='alice')
        return str(response)
    
    # Record the call
    response.say("You have reached a temporary number. Your message will be recorded.", voice='alice')
    response.record(
        action=url_for('voice_recording_complete', _external=True),
        method='POST',
        max_length=60,
        play_beep=True
    )
    
    return str(response)

@app.route('/webhook/voice/recording', methods=['POST'])
def voice_recording_complete():
    """Handle completed call recording"""
    from_number = request.form.get('From')
    to_number = request.form.get('To')
    recording_url = request.form.get('RecordingUrl')
    recording_duration = request.form.get('RecordingDuration', 0)
    call_sid = request.form.get('CallSid')
    
    # Find the phone
    phone = PhoneNumber.query.filter_by(number=to_number).first()
    
    if phone:
        message = Message(
            phone_number_id=phone.id,
            from_number=from_number,
            to_number=to_number,
            body=f"[Call Recording - {recording_duration}s]",
            call_recording_url=recording_url,
            call_duration=int(recording_duration),
            message_type='call'
        )
        db.session.add(message)
        db.session.commit()
    
    return str(VoiceResponse())

# ==================== MAINTENANCE ====================

def cleanup_expired_numbers():
    """Background thread to clean up expired numbers"""
    while True:
        with app.app_context():
            expired = PhoneNumber.query.filter(
                PhoneNumber.expires_at <= datetime.utcnow(),
                PhoneNumber.is_active == True
            ).all()
            
            for number in expired:
                number.is_active = False
            
            db.session.commit()
        
        time.sleep(300)  # Run every 5 minutes

# ==================== MAIN ====================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_expired_numbers, daemon=True)
    cleanup_thread.start()
    
    app.run(debug=True, host='0.0.0.0', port=5000)
