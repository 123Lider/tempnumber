import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-this-to-a-random-secret')
    
    # Twilio Credentials (Sign up at twilio.com)
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '18d7671fc10a8ade4e0a0d17164d473e')
    TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '+8801627346558')
    
    # Database (SQLite for dev, PostgreSQL for production)
    DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///messages.db')
