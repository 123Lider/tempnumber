import os
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-change-this-12345'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tempnum.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ==================== DATABASE MODELS ====================

class UserNumber(db.Model):
    """User's registered number that will receive SMS"""
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)
    display_name = db.Column(db.String(100), default='My Number')
    api_token = db.Column(db.String(64), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    country_code = db.Column(db.String(5), default='+880')  # Bangladesh default
    messages = db.relationship('SMSMessage', backref='number', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'display_name': self.display_name,
            'api_token': self.api_token,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'message_count': len(self.messages)
        }

class SMSMessage(db.Model):
    """Received SMS messages"""
    id = db.Column(db.Integer, primary_key=True)
    number_id = db.Column(db.Integer, db.ForeignKey('user_number.id'), nullable=False)
    sender = db.Column(db.String(50), nullable=False)
    body = db.Column(db.Text, nullable=False)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'sender': self.sender,
            'body': self.body,
            'received_at': self.received_at.isoformat(),
            'is_read': self.is_read,
            'number_id': self.number_id
        }

class RegisteredDevice(db.Model):
    """Android devices registered for forwarding"""
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), unique=True, nullable=False)
    device_name = db.Column(db.String(100))
    number_id = db.Column(db.Integer, db.ForeignKey('user_number.id'), nullable=False)
    is_online = db.Column(db.Boolean, default=False)
    last_heartbeat = db.Column(db.DateTime, default=datetime.utcnow)
    
    number_rel = db.relationship('UserNumber', backref='devices')

# ==================== AUTH MIDDLEWARE ====================

def require_api_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-API-Token')
        if not token:
            return jsonify({'error': 'Missing API token'}), 401
        
        number = UserNumber.query.filter_by(api_token=token, is_active=True).first()
        if not number:
            return jsonify({'error': 'Invalid or inactive token'}), 401
        
        # Update last seen
        number.last_seen = datetime.utcnow()
        db.session.commit()
        
        return f(number, *args, **kwargs)
    return decorated

# ==================== WEB ROUTES ====================

@app.route('/')
def index():
    """Homepage"""
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    """User dashboard"""
    numbers = UserNumber.query.filter_by(is_active=True).order_by(desc(UserNumber.created_at)).all()
    return render_template('dashboard.html', numbers=numbers)

@app.route('/number/<int:number_id>')
def view_number(number_id):
    """View messages for a specific number"""
    number = UserNumber.query.get_or_404(number_id)
    messages = SMSMessage.query.filter_by(number_id=number_id)\
        .order_by(desc(SMSMessage.received_at)).all()
    
    # Mark all as read
    for msg in messages:
        if not msg.is_read:
            msg.is_read = True
    db.session.commit()
    
    return render_template('inbox.html', number=number, messages=messages)

@app.route('/number/new', methods=['POST'])
def register_number():
    """Register a new number"""
    number = request.form.get('number', '').strip()
    display_name = request.form.get('display_name', 'My Number')
    
    if not number:
        flash('Phone number is required!', 'danger')
        return redirect(url_for('dashboard'))
    
    # Clean the number
    number = number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    
    # Check if already exists
    existing = UserNumber.query.filter_by(number=number).first()
    if existing:
        flash(f'Number {number} is already registered!', 'warning')
        return redirect(url_for('dashboard'))
    
    # Generate API token
    api_token = secrets.token_hex(32)
    
    new_number = UserNumber(
        number=number,
        display_name=display_name,
        api_token=api_token
    )
    
    db.session.add(new_number)
    db.session.commit()
    
    flash(f'Number registered successfully! Save your API token: {api_token}', 'success')
    return redirect(url_for('view_number', number_id=new_number.id))

@app.route('/number/<int:number_id>/delete', methods=['POST'])
def delete_number(number_id):
    """Deactivate a number"""
    number = UserNumber.query.get_or_404(number_id)
    number.is_active = False
    db.session.commit()
    
    flash(f'Number {number.number} has been deactivated', 'info')
    return redirect(url_for('dashboard'))

@app.route('/number/<int:number_id>/regenerate-token', methods=['POST'])
def regenerate_token(number_id):
    """Regenerate API token"""
    number = UserNumber.query.get_or_404(number_id)
    number.api_token = secrets.token_hex(32)
    db.session.commit()
    
    flash(f'New API token: {number.api_token}', 'success')
    return redirect(url_for('view_number', number_id=number_id))

# ==================== API ENDPOINTS (SMS INCOMING) ====================

@app.route('/api/sms/receive', methods=['POST'])
@require_api_token
def receive_sms(number):
    """Receive SMS from Android device"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
    
    sender = data.get('sender', 'Unknown')
    body = data.get('body', '')
    device_id = data.get('device_id', 'unknown')
    
    if not body:
        return jsonify({'error': 'Message body required'}), 400
    
    # Save the message
    message = SMSMessage(
        number_id=number.id,
        sender=sender,
        body=body
    )
    
    db.session.add(message)
    db.session.commit()
    
    # Real-time notification via WebSocket
    socketio.emit('new_sms', {
        'number_id': number.id,
        'number': number.number,
        'sender': sender,
        'body': body[:100],
        'message_id': message.id,
        'time': message.received_at.isoformat()
    }, room=f'number_{number.id}')
    
    # Also emit to admin room
    socketio.emit('new_sms', {
        'number_id': number.id,
        'number': number.number,
        'sender': sender,
        'body': body[:100],
        'message_id': message.id,
        'time': message.received_at.isoformat()
    }, room='admin')
    
    return jsonify({'success': True, 'message_id': message.id})

@app.route('/api/sms/bulk', methods=['POST'])
@require_api_token
def receive_bulk_sms(number):
    """Receive bulk SMS messages"""
    data = request.get_json()
    messages_data = data.get('messages', [])
    
    if not messages_data:
        return jsonify({'error': 'No messages provided'}), 400
    
    saved = []
    for msg_data in messages_data:
        message = SMSMessage(
            number_id=number.id,
            sender=msg_data.get('sender', 'Unknown'),
            body=msg_data.get('body', '')
        )
        db.session.add(message)
        saved.append({
            'sender': message.sender,
            'body': message.body[:50],
            'message_id': message.id
        })
        
        # Real-time notification
        socketio.emit('new_sms', {
            'number_id': number.id,
            'number': number.number,
            'sender': message.sender,
            'body': message.body[:100],
            'message_id': message.id,
            'time': message.received_at.isoformat()
        }, room=f'number_{number.id}')
    
    db.session.commit()
    
    return jsonify({'success': True, 'count': len(saved), 'messages': saved})

@app.route('/api/messages/<int:number_id>')
def get_messages_api(number_id):
    """Get all messages for a number (API)"""
    number = UserNumber.query.get_or_404(number_id)
    messages = SMSMessage.query.filter_by(number_id=number_id)\
        .order_by(desc(SMSMessage.received_at)).limit(50).all()
    
    return jsonify([m.to_dict() for m in messages])

@app.route('/api/device/heartbeat', methods=['POST'])
@require_api_token
def device_heartbeat(number):
    """Android device heartbeat"""
    data = request.get_json()
    device_id = data.get('device_id', 'unknown')
    device_name = data.get('device_name', 'Android Device')
    
    device = RegisteredDevice.query.filter_by(device_id=device_id).first()
    
    if not device:
        device = RegisteredDevice(
            device_id=device_id,
            device_name=device_name,
            number_id=number.id
        )
        db.session.add(device)
    
    device.is_online = True
    device.last_heartbeat = datetime.utcnow()
    device.number_id = number.id
    db.session.commit()
    
    socketio.emit('device_status', {
        'number_id': number.id,
        'device_id': device_id,
        'is_online': True
    }, room='admin')
    
    return jsonify({'success': True, 'device_id': device_id})

# ==================== API ENDPOINTS (PUBLIC) ====================

@app.route('/api/public/numbers')
def public_numbers():
    """List active numbers (public)"""
    numbers = UserNumber.query.filter_by(is_active=True)\
        .order_by(desc(UserNumber.last_seen)).all()
    
    return jsonify([{
        'id': n.id,
        'number': n.number,
        'display_name': n.display_name,
        'message_count': len(n.messages),
        'is_online': any(d.is_online for d in n.devices) if n.devices else False
    } for n in numbers])

@app.route('/api/public/messages/<int:number_id>')
def public_messages(number_id):
    """Get messages for a number (public, last 10)"""
    number = UserNumber.query.get_or_404(number_id)
    
    if not number.is_active:
        return jsonify({'error': 'Number not found'}), 404
    
    messages = SMSMessage.query.filter_by(number_id=number_id)\
        .order_by(desc(SMSMessage.received_at)).limit(10).all()
    
    return jsonify([{
        'id': m.id,
        'sender': m.sender,
        'body': m.body,
        'received_at': m.received_at.isoformat()
    } for m in messages])

# ==================== WEBSOCKET EVENTS ====================

@socketio.on('join')
def on_join(data):
    """Join a number's room"""
    number_id = data.get('number_id')
    if number_id:
        join_room(f'number_{number_id}')

@socketio.on('leave')
def on_leave(data):
    """Leave a number's room"""
    number_id = data.get('number_id')
    if number_id:
        leave_room(f'number_{number_id}')

@socketio.on('join_admin')
def on_join_admin():
    """Join admin room"""
    join_room('admin')

# ==================== MAIN ====================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    print("=" * 50)
    print("TempNum Server Started!")
    print("=" * 50)
    print("Website: http://localhost:5000")
    print("=" * 50)
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
