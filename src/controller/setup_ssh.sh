#!/bin/bash

# Setup SSH server in the test pod for live migration
# This script configures SSH access to enable live migration tracking

echo "Setting up SSH server for live migration..."

# Install SSH server
apt-get update && apt-get install -y openssh-server

# Configure SSH
mkdir -p /var/run/sshd
echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config
echo 'PubkeyAuthentication yes' >> /etc/ssh/sshd_config

# Set root password (for testing purposes)
echo 'root:password123' | chpasswd

# Generate SSH host keys if they don't exist
if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then
    ssh-keygen -A
fi

# Start SSH server
/usr/sbin/sshd -D &

echo "SSH server started on port 22"
echo "You can now SSH into this pod using: ssh root@<pod-ip>"
echo "Password: password123"

# Keep the container running
exec /app/simple_test.sh
