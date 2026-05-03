# TempNum - Temporary Phone Number Service

A Flask-based web application for generating and managing temporary phone numbers for SMS and call receiving.

## Features
- Generate temporary US phone numbers
- Receive SMS messages
- Receive phone calls with recording
- Auto-expiration of numbers
- Real-time inbox updates via WebSocket
- REST API with key authentication
- Rate limiting protection
- Docker deployment support

## Quick Start

```bash
git clone https://github.com/123Lider/tempnumber.git
cd tempnumber
pip install -r requirements.txt
python app.py
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/numbers` | List active numbers |
| POST | `/api/numbers/bulk` | Generate bulk numbers |
| GET | `/api/numbers/<id>/messages` | Get messages for a number |

## Pentesting Use Cases
- OTP bypass testing
- Social engineering simulations
- SMS/API integration testing
- Anonymous communication channels
