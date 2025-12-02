#!/bin/bash
# Deploy TwistedTV Pi Client to Raspberry Pi

set -e

PI_USER="twistedtv"
PI_HOST="192.168.1.201"
PI_PATH="/home/twistedtv/twistedtv-pi-client"

echo "Deploying TwistedTV Pi Client to ${PI_USER}@${PI_HOST}..."

# Sync all files except node_modules and large files
rsync -av --exclude 'node_modules' \
  --exclude '.next' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  ../  ${PI_USER}@${PI_HOST}:${PI_PATH}/

echo "Deployment complete!"
echo ""
echo "Next steps on the Pi:"
echo "1. cd ${PI_PATH}"
echo "2. source ~/venv_daily/bin/activate  # If using existing venv"
echo "3. pip install -r requirements.txt"
echo "4. cd frontend && npm install"
echo "5. npm run build  # For production"
