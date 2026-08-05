# ---- 构建阶段 ----
FROM node:18-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
RUN npm run build

# ---- 运行阶段（nginx 托管静态文件）----
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

# SPA 路由回退到 index.html
RUN echo 'server { \
    listen 80; \
    server_name _; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { \
        try_files $uri $uri/ /index.html; \
    } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
