FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
RUN printf 'server {\n listen 80;\n location /api/ { proxy_pass http://backend:8000/api/; }\n location /health { proxy_pass http://backend:8000/health; }\n location / { root /usr/share/nginx/html; try_files $uri /index.html; }\n}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
