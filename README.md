# TempNum - Temporary Phone Number Service

A Flask-based web application for generating and managing temporary phone numbers for SMS and call receiving.

## Features

- Generate temporary US phone numbers
- Receive SMS messages with media attachments
- Receive phone calls with audio recording
- Auto-expiration of numbers
- Real-time inbox updates via WebSocket
- REST API with key authentication
- Rate limiting protection
- Docker deployment support
- Bulk number generation

## Quick Start

```bash
# Clone the repository
git clone https://github.com/123Lider/tempnumber.git
cd tempnumber

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py

# Visit http://localhost:5000
