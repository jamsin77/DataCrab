# 公网部署加固

## 1. 环境变量
复制 `backend/.env.example` 为 `backend/.env`（或项目根 `.env`），生成并填写：

```bash
openssl rand -hex 32   # JWT_SECRET_KEY
openssl rand -hex 32   # INTERNAL_API_TOKEN
openssl rand -hex 32   # ENCRYPT_KEY
```

## 2. 启动
```bash
docker compose up -d --build
```

## 3. HTTPS
- 把证书放到 `certs/fullchain.pem` 和 `certs/privkey.pem`；
- 将 `nginx/nginx.conf` 替换为 `nginx/nginx.production.conf`，并把 `server_name` 改成正式域名；
- 国内公网服务需先完成域名 ICP 备案。

## 4. 备份
```bash
crontab -e
# 每天 02:00 备份
0 2 * * * /root/datacrab/deploy/backup.sh
```

## 5. 服务器加固
```bash
chmod +x deploy/harden_server.sh
sudo ./deploy/harden_server.sh
```

## 6. 上线检查
- 管理员已改密；
- 注册接口返回 404/403；
- 内部接口返回 404/403；
- PostgreSQL/Redis/MinIO 端口公网不可达；
- HTTPS 已生效；
- 登录/聊天接口已限流；
- 备份恢复演练通过。
