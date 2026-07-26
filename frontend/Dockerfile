# Прод-образ фронтенда: сборка Vite → раздача через nginx с прокси на api.
# Платформа amd64 (прод-цель Astra/x86-64). Офлайн: базовые образы заранее
# загрузить в локальный кэш (docker save/load).
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# Общие маршруты (include), HTTP-конфиг по умолчанию, TLS-конфиг про запас.
COPY nginx.locations.conf /etc/nginx/dashbord-locations.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx.tls.conf /etc/nginx/dashbord-tls.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
