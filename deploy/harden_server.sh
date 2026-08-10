#!/usr/bin/env bash
# 公网服务器基础加固脚本（Ubuntu/Debian）
# 仅在全新云主机上执行，执行前确认当前 SSH 会话不会断连
set -euo pipefail

# 1. 防火墙：只放行 SSH、HTTP、HTTPS
apt-get update
apt-get install -y ufw fail2ban unattended-upgrades
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# 2. SSH 加固（谨慎：确保已配置密钥登录再执行）
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# 3. fail2ban 防暴力破解
systemctl enable fail2ban
systemctl restart fail2ban

# 4. 自动安全更新
echo 'APT::Periodic::Update-Package-Lists "1";' > /etc/apt/apt.conf.d/20auto-upgrades
echo 'APT::Periodic::Unattended-Upgrade "1";' >> /etc/apt/apt.conf.d/20auto-upgrades
systemctl restart unattended-upgrades || true

echo "server hardening done"
